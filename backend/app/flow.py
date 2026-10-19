from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, store
from .brief.cohorts import plan_cohorts
from .brief.contact import build_contact_sheet
from .brief.fastplan import plan_cohorts_fast, plan_cohorts_llm
from .brief.shortlist import validate_affinity
from .compose.composer import apply_fix, compose, parse_frac_rects, strip_text_and_logo
from .compose.wireframe import build_wireframe_png
from .fidelity.manifest import build_manifest
from .fidelity.textfit import apply_measured, mark_replaceable, measure_overlays, replacement_plan
from .ingest.pipeline import run_ingest
from .judge.critic import judge, verify_strip
from .judge.layout_tune import tune_placement
from .models import Brief, Cohort, EditDraft, Job, TrailItem, Variant

_lock = threading.Lock()
_fin_locks: dict[str, threading.Lock] = {}


def _flock(key: str) -> threading.Lock:
    with _lock:
        return _fin_locks.setdefault(key, threading.Lock())


def _log(job: Job, msg: str):
    with _lock:
        job.log.append(msg)


def _image_size(path: str) -> tuple[int, int]:
    from PIL import Image

    try:
        return Image.open(path).size
    except Exception:
        return 1024, 1024
        store.save_job(job.brand_id, job)


def _trail(job: Job, stage: str, label: str, variant_id: str = "", image: str = "", score=None, notes=None):
    def rel(p):
        s = str(p)
        i = s.find("workspace/")
        return s[i:] if i >= 0 else s

    with _lock:
        job.trail.append(
            TrailItem(
                id=f"{len(job.trail)+1}",
                stage=stage,
                label=label,
                variant_id=variant_id,
                image=rel(image) if image else "",
                score=score,
                notes=notes or [],
                ts=time.time(),
            )
        )
        store.save_job(job.brand_id, job)


def ingest(brand_id: str, root: str, on_log=None) -> dict:
    return run_ingest(brand_id, root, on_log=on_log)


def _cohort_to_brief(job: Job, c: Cohort) -> Brief:
    return Brief(
        job_id=job.id,
        use_case=job.use_case,
        ratio=job.ratio,
        archetype=c.name,
        recipe_id=c.recipe_id,
        story=c.story,
        idea=c.idea,
        color_story=c.color_story,
        copy=c.copy,
        boldness=c.boldness,
        slots=c.slots,
        zones=c.zones,
    )


def create_job(brand_id: str, use_case: str, ratio: str = "1:1", n_variants: int = 4, folder: str = "") -> Job:
    import uuid

    job = Job(
        id=f"job_{uuid.uuid4().hex[:10]}",
        brand_id=brand_id,
        folder=folder,
        use_case=use_case,
        ratio=ratio,
        n_variants=max(1, min(6, n_variants)),
    )
    store.save_job(brand_id, job)
    return job


def run_job(job_id: str, brand_id: str | None = None, ratio: str | None = None) -> Job:
    """Fast path: local planning → parallel compose → done.

    Everything expensive beyond the image call (judge loop, strip, measured
    placement) runs in a background refine thread so the first images land as
    soon as the image model returns (~seconds).
    """
    bid = brand_id
    if not bid:
        found = store.find_job(job_id)
        if not found:
            raise ValueError(f"unknown job {job_id}")
        bid, _ = found
    job = store.load_job(bid, job_id)
    if not job:
        raise ValueError(f"unknown job {job_id}")
    if ratio:
        job.ratio = ratio
    grammar = store.load_grammar(bid)
    jdir = store.job_dir(bid, job.id)

    job.status = "briefing"
    job.trail = []
    job.variants = []
    job.edits = []
    job.selected = ""
    job.error = ""
    job.log = []
    job.refining = False
    store.save_job(bid, job)
    n_var = max(1, min(6, job.n_variants or 4))

    t0 = time.time()
    _log(job, f"designing {n_var} concepts — LLM wants + retrieval ({config.ASSETS_PER_COMPOSITION} fixed assets each, folder='{job.folder or 'all'}')")
    _trail(job, "brief", f"designing {n_var} distinct concepts")
    cohorts: list[Cohort] = []
    if config.DEEP_PLAN:
        cohorts = plan_cohorts(bid, job.use_case, grammar, n=n_var, folder=job.folder)
    else:
        try:
            cohorts = plan_cohorts_llm(bid, job.use_case, grammar, n=n_var, folder=job.folder)
        except Exception as e:
            _log(job, f"LLM design planning failed ({str(e)[:80]}) — local fallback")
        if not cohorts:
            cohorts = plan_cohorts_fast(bid, job.use_case, grammar, n=n_var, folder=job.folder)
        if not cohorts:
            _log(job, "local planner found no usable assets — falling back to thinking model")
            cohorts = plan_cohorts(bid, job.use_case, grammar, n=n_var, folder=job.folder)
    _log(job, f"planned {len(cohorts)} cohorts in {time.time() - t0:.2f}s")
    _trail(
        job,
        "brief",
        "cohort stories + asset sets locked",
        notes=[f"{c.name} [{c.angle}]: {c.story[:56]}" for c in cohorts],
    )

    def _pick_reference() -> "store.Asset | None":
        """Explicit re-skin requests only ('layerize this', 'keep the design'…):
        then a reference photo/template asset IS the design. Otherwise the image
        model CREATES the design from refs + wireframe (the consistency path)."""
        import re as _re

        if not _re.search(r"(?i)(re-?skin|layerize|keep (the )?design|replace (the )?text in|in-?place replace)", job.use_case):
            return None
        from .rag import retrieve

        cands = [a for a in store.load_catalog(bid) if a.kind in ("photo-scene", "template") and a.png and Path(a.png).exists()]
        if not cands:
            return None
        by_id = {a.id: a for a in cands}
        for h in retrieve(bid, job.use_case, k=6):
            if h.id in by_id:
                return by_id[h.id]
        return cands[0]

    base_ref = _pick_reference()

    def run_variant(i: int, cohort: Cohort) -> Variant:
        vid = f"{job.id}_v{i+1}"
        variant = Variant(id=vid, prompt=f"{cohort.angle} | {cohort.name}")
        brief = _cohort_to_brief(job, cohort)
        variant.brief = brief

        _log(job, f"{vid}: idea '{cohort.name}' — {cohort.story[:60]}")
        problems = validate_affinity(bid, brief, grammar)
        if problems:
            _log(job, f"{vid}: affinity warnings {problems}")

        contact = jdir / f"{vid}_contact.png"
        build_contact_sheet(bid, brief, contact)
        refs = [store.get_asset(bid, f.asset_id).png for f in brief.slots if store.get_asset(bid, f.asset_id)]
        _trail(
            job,
            "contact",
            f"{vid.split('_')[-1]}: cohort {len({s.asset_id for s in brief.slots})} assets · {brief.color_story[:40]}",
            vid,
            str(contact),
            notes=[f"{s.role}→{s.asset_id}: {s.why[:48]}" for s in brief.slots],
        )

        with _lock:
            job.status = "composing"
        img = jdir / f"{vid}_design.png"
        # Explicit re-skin mode only (see _pick_reference): the reference image
        # IS the design. Otherwise the image model CREATES from refs + wireframe.
        ref = base_ref
        if ref:
            img.write_bytes(Path(ref.png).read_bytes())
            variant.ref_base = True
            _log(job, f"{vid}: reference base '{ref.name}' — layerize & replace in place")
        else:
            _log(job, f"{vid}: composing — idea: {cohort.idea[:60]}")
            # consistency mechanism: the WIREFRAME goes out WITH the refs — the
            # image model's job is to realize exactly what we expect.
            wf = jdir / f"{vid}_wireframe.png"
            try:
                build_wireframe_png(brief, wf)
                _trail(job, "contact", f"{vid.split('_')[-1]}: wireframe locked ({len(brief.zones)} zones)", vid, str(wf))
            except Exception as e:
                wf = None
                _log(job, f"{vid}: wireframe render skipped ({str(e)[:60]})")
            compose(brief, grammar, str(contact), img, refs, brand_id=bid, wireframe=str(wf) if wf else "")
        variant.image = str(img)
        variant.status = "done"
        _trail(
            job,
            "compose",
            f"{vid.split('_')[-1]}: first design ({cohort.name})",
            vid,
            str(img),
            notes=[cohort.idea[:64], brief.copy.headline],
        )
        return variant

    # parallel compose — publish each variant the moment it lands
    with ThreadPoolExecutor(max_workers=max(1, n_var)) as pool:
        futs = {pool.submit(run_variant, i, c): i for i, c in enumerate(cohorts)}
        done_map: dict[int, Variant] = {}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                done_map[i] = fut.result()
            except Exception as e:
                _log(job, f"v{i + 1} failed: {e}")
                done_map[i] = Variant(id=f"{job.id}_v{i + 1}", status="failed", prompt=str(e))
            with _lock:
                job.variants = [done_map[k] for k in sorted(done_map)]
                store.save_job(bid, job)

    variants = [done_map[k] for k in sorted(done_map)]
    job.variants = variants
    ok = [v for v in variants if v.image]
    if not ok:
        job.status = "failed"
        job.error = "all variants failed to compose"
        store.save_job(bid, job)
        return job

    job.status = "selecting"
    winner = max(ok, key=lambda v: len(v.brief.slots) if v.brief else 0)
    job.selected = winner.id
    _log(job, f"selected {winner.id}")
    _trail(job, "select", f"winner: {winner.brief.story[:48] if winner.brief else winner.id}", winner.id, winner.image)

    # instant pending canvas (zone placement) — real layer extraction lands in background
    job.status = "delivering"
    manifest = build_manifest(bid, job.id, winner.id, winner.image, winner.brief)
    manifest.pending_layers = True
    for l in manifest.layers:
        if l.type == "text":
            l.baked = True
    manifest_path = jdir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2))
    job.edits = [
        EditDraft(
            id="generated",
            parent="",
            instruction=job.use_case,
            kind="generate",
            image=winner.image,
            manifest=str(manifest_path),
            status="done",
            created=time.time(),
            notes=[f"winner {winner.id}", "layers extracting in background…"],
        )
    ]
    job.status = "done"
    _log(job, f"images ready in {time.time() - t0:.1f}s — layer extraction + judging stream in below")
    _trail(job, "manifest", "canvas preview (layer extraction running…)", winner.id, winner.image, notes=[f"{l.type}:{l.role}" for l in manifest.layers])
    store.save_job(bid, job)

    threading.Thread(target=_refine_safe, args=(bid, job.id), daemon=True).start()
    return job


def _refine_safe(brand_id: str, job_id: str):
    """Background polish: strip+measure the winner, then judge/fix every variant."""
    try:
        job = store.load_job(brand_id, job_id)
        if not job:
            return
        job.refining = True
        store.save_job(brand_id, job)

        finalize_job(brand_id, job_id)

        job = store.load_job(brand_id, job_id)
        grammar = store.load_grammar(brand_id)
        for v in list(job.variants):
            if not v.image or not v.brief:
                continue
            try:
                _refine_variant(job, v, grammar)
            except Exception as e:
                _log(job, f"{v.id} judge skipped: {e}")

        # winner may have changed via fixes — rebuild editable canvas if so
        job = store.load_job(brand_id, job_id)
        winner = next((v for v in job.variants if v.id == job.selected), None)
        if winner and winner.history:
            finalize_job(brand_id, job_id, force=True)

        job = store.load_job(brand_id, job_id)
        job.refining = False
        store.save_job(brand_id, job)
        _log(job, "refine complete — judged, stripped, layers live")
        _trail(job, "variant", "refine complete (scores + layers final)", job.selected, winner.image if winner else "", score=winner.best_report.score if winner and winner.best_report else None)
    except Exception as e:
        try:
            job = store.load_job(brand_id, job_id)
            if job:
                job.refining = False
                job.log.append(f"refine error: {e}")
                store.save_job(brand_id, job)
        except Exception:
            pass


def _refine_variant(job: Job, variant: Variant, grammar) -> None:
    from . import store as _store

    bid = job.brand_id
    brief = variant.brief
    jdir = _store.job_dir(bid, job.id)
    best_score, best_path = -1.0, variant.image
    current = Path(variant.image)
    prev_score = None
    for rnd in range(config.MAX_JUDGE_ROUNDS):
        _log(job, f"{variant.id}: judge round {rnd + 1}")
        report = judge(str(current), brief, grammar, brand_id=bid)
        variant.reports.append(report)
        fails = [i.check for i in report.items if not i.pass_]
        _log(job, f"{variant.id}: score {report.score} fails={fails}")
        _trail(
            job,
            "judge",
            f"{variant.id.split('_')[-1]}: judge round {rnd + 1}",
            variant.id,
            str(current),
            score=report.score,
            notes=[f"{i.check}: {i.note[:56]}" for i in report.items if not i.pass_],
        )
        if report.score > best_score:
            best_score, best_path = report.score, str(current)
        last = rnd == config.MAX_JUDGE_ROUNDS - 1
        stagnant = prev_score is not None and report.score <= prev_score
        if report.score >= 92 or not report.fixes or last or stagnant or variant.ref_base:
            # reference re-skins: score only — a whole-image fix would redraw the
            # design and violate "keep the design intact"
            break
        prev_score = report.score
        _log(job, f"{variant.id}: fixing — {report.fixes[0][:80]}")
        nxt = jdir / f"{variant.id}_fix{rnd + 1}.png"
        apply_fix(brief, current, nxt, report.fixes[0])
        current = nxt
        variant.history.append(str(nxt))
        _trail(job, "fix", f"{variant.id.split('_')[-1]}: fix {rnd + 1}", variant.id, str(nxt), notes=[report.fixes[0][:72]])
    variant.image = best_path
    variant.best_report = max(variant.reports, key=lambda r: r.score) if variant.reports else None
    variant.status = "done"
    with _lock:
        store.save_job(bid, job)


def finalize_job(brand_id: str, job_id: str, force: bool = False):
    """Strip baked text/logo, measure placement, write the real editable manifest."""
    with _flock(f"{brand_id}:{job_id}"):
        job = store.load_job(brand_id, job_id)
        if not job:
            return
        gen = next((e for e in job.edits if e.id == "generated"), None)
        if gen and gen.manifest and not force:
            try:
                import json

                m = json.loads(Path(gen.manifest).read_text())
                if m and not m.get("pending_layers"):
                    return  # already finalized
            except Exception:
                pass
        winner = next((v for v in job.variants if v.id == job.selected), None) or (job.variants[0] if job.variants else None)
        if not winner or not winner.image or not winner.brief:
            return
        grammar = store.load_grammar(brand_id)
        jdir = store.job_dir(brand_id, job.id)

        _log(job, "finalizing canvas: replacement plan + measured placement")
        typo = grammar.typography or {}
        font_hint = typo.get("headline_font") or typo.get("body_font") or ""
        plan = replacement_plan(winner.brief, brand_id, font_hint)
        winner.brief = mark_replaceable(winner.brief, plan)
        _log(job, "replacement plan: " + ", ".join(f"{r}={'REPLACE' if p['replace'] else 'keep baked'} [{p['reason']}]" for r, p in plan.items()))
        _log(job, "measuring baked text/logo pixels (vision windows + deterministic CV)")
        measured = measure_overlays(winner.image, winner.brief, font_hint=font_hint)
        if measured:
            winner.brief = apply_measured(winner.brief, measured)
        else:
            _log(job, "measurement empty — falling back to vision placement tune")
            winner.brief = tune_placement(winner.image, winner.brief)
        _trail(
            job,
            "tune",
            f"placement locked to measured pixels ({len(measured)} overlays: exact pos/size/colour)",
            winner.id,
            winner.image,
            notes=[f"{r}: {[round(v, 3) for v in m['bbox']]}" for r, m in measured.items()],
        )

        # REPLACE PASS (deterministic, direct — no RAG): text blocks and
        # text-bearing logos only. Remove them from the bake, then re-render
        # text with the brand font and paste the direct logo asset — each in
        # the SAME bbox it occupied. Everything else stays as generated.
        _log(job, "replace pass: text (brand font) + logos (direct assets) at measured bboxes")

        stripped = jdir / f"{winner.id}_stripped.png"
        _log(job, "removing baked text/logo (image model, masked windows)")
        strip_text_and_logo(winner.brief, Path(winner.image), stripped)
        _trail(job, "strip", "removed exact text + logo (become live layers)", winner.id, str(stripped), notes=[z.content or z.role for z in winner.brief.zones])

        clean, leftovers = verify_strip(str(stripped), winner.brief)
        if not clean and leftovers:
            _log(job, f"strip verify: {len(leftovers)} leftovers — re-stripping")
            joined = "; ".join(leftovers[:4])
            extra_rects = parse_frac_rects(joined)
            nxt = jdir / f"{winner.id}_strip2.png"
            strip_text_and_logo(winner.brief, Path(stripped), nxt, extra_rects=extra_rects, extra_notes=joined)
            stripped = nxt
            _trail(job, "strip", "re-strip round 2", winner.id, str(stripped), notes=leftovers[:3])

        manifest = build_manifest(brand_id, job.id, winner.id, str(stripped), winner.brief)
        manifest.pending_layers = False
        winner.manifest = manifest

        # fit copy into the measured boxes with real font metrics, then judge the
        # SCREENSHOT of the canvas and adjust size/position (the designer loop)
        rendered = jdir / f"{winner.id}_rendered.png"
        try:
            from .fidelity.render import polish_overlays

            notes = polish_overlays(str(stripped), manifest, str(rendered))
            _log(job, "overlays: " + ("; ".join(notes) if notes else "fitted to measured boxes"))
        except Exception as e:
            _log(job, f"overlay polish skipped: {e}")
            rendered = None

        manifest_path = jdir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2))

        gen = next((e for e in job.edits if e.id == "generated"), None)
        if gen:
            gen.image = str(stripped)
            gen.manifest = str(manifest_path)
            gen.notes = [f"winner {winner.id}", f"score {winner.best_report.score if winner.best_report else ''}"]
        else:
            job.edits.insert(
                0,
                EditDraft(
                    id="generated",
                    parent="",
                    instruction=job.use_case,
                    kind="generate",
                    image=str(stripped),
                    manifest=str(manifest_path),
                    status="done",
                    created=time.time(),
                ),
            )
        _log(job, "manifest written — design stripped, text/logo as layers; click Edit to iterate")
        _trail(job, "manifest", f"editable canvas: {len(manifest.layers)} layers", winner.id, str(rendered or stripped), notes=[f"{l.type}:{l.role}" for l in manifest.layers])
        with _lock:
            store.save_job(brand_id, job)


def ensure_finalized(brand_id: str, job_id: str) -> None:
    """Make the editable canvas ready (runs the background finalize synchronously if needed)."""
    job = store.load_job(brand_id, job_id)
    if not job:
        return
    gen = next((e for e in job.edits if e.id == "generated"), None)
    if gen and gen.manifest and Path(gen.manifest).exists():
        try:
            import json

            m = json.loads(Path(gen.manifest).read_text())
            if not m.get("pending_layers"):
                return
        except Exception:
            pass
    finalize_job(brand_id, job_id)


def run_full(brand_id: str, use_case: str, ratio: str = "1:1", folder: str = "") -> Job:
    job = create_job(brand_id, use_case, ratio, folder=folder)
    return run_job(job.id, brand_id, ratio)
