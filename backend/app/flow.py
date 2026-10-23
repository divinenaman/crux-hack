from pathlib import Path
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, edits, store
from .brief.cohorts import plan_cohorts
from .brief.contact import build_contact_sheet
from .brief.fastplan import plan_cohorts_fast, plan_cohorts_llm
from .brief.placements import placements_from_zones
from .compose.fill import fill_background
from .fidelity.manifest import build_manifest
from .layout.canvas import render_composite, render_layout
from .ingest.pipeline import run_ingest
from .models import Brief, Cohort, EditDraft, Job, TrailItem, Variant

_lock = threading.Lock()
_fin_locks: dict[str, threading.Lock] = {}


def _flock(key: str) -> threading.Lock:
    with _lock:
        return _fin_locks.setdefault(key, threading.Lock())


def _log(job: Job, msg: str):
    with _lock:
        job.log.append(msg)


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
    brief = Brief(
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
        placements=c.placements,
        bg_fields=c.bg_fields,
        bg_story=c.bg_story,
        palette_refs=c.palette_refs,
    )
    if not brief.placements and brief.zones:
        pl, fl = placements_from_zones(brief.zones, brief.copy)
        brief = brief.model_copy(update={"placements": pl, "bg_fields": fl or brief.bg_fields})
    return brief


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
    """Layout-first pipeline, per variant (in parallel):

        plan → wireframe (pieces positioned on a blank canvas)
             → background fill (image model paints the whole scene from the
               wireframe as reference, leaving clean colour fields under pieces)
             → composite (bg at the bottom, real pieces on top in code)
             → winner manifest (bg raster + live layers — separation by construction)
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
    _log(job, f"designing {n_var} layout concepts (placements + colour-control fields), folder='{job.folder or 'all'}'")
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
    # deep-planner cohorts carry zones only — bridge to placements
    fixed: list[Cohort] = []
    for c in cohorts:
        if not c.placements and c.zones:
            pl, fl = placements_from_zones(c.zones, c.copy)
            c = c.model_copy(update={"placements": pl, "bg_fields": fl or c.bg_fields})
        if c.placements:
            fixed.append(c)
    cohorts = fixed
    _log(job, f"planned {len(cohorts)} layout cohorts in {time.time() - t0:.2f}s")
    _trail(
        job,
        "brief",
        "layout specs + colour-control fields locked",
        notes=[f"{c.name} [{c.angle}]: {len(c.placements)} pieces · {c.color_story[:40]}" for c in cohorts],
    )

    def run_variant(i: int, cohort: Cohort) -> Variant:
        vid = f"{job.id}_v{i+1}"
        variant = Variant(id=vid, prompt=f"{cohort.angle} | {cohort.name}")
        brief = _cohort_to_brief(job, cohort)
        variant.brief = brief

        _log(job, f"{vid}: idea '{cohort.name}' — {cohort.story[:60]}")

        contact = jdir / f"{vid}_contact.png"
        try:
            build_contact_sheet(bid, brief, contact)
            _trail(
                job,
                "contact",
                f"{vid.split('_')[-1]}: {len({s.asset_id for s in brief.slots})} element refs · {brief.color_story[:40]}",
                vid,
                str(contact),
                notes=[f"{s.role}→{s.asset_id}: {s.why[:48]}" for s in brief.slots],
            )
        except Exception as e:
            _log(job, f"{vid}: contact sheet skipped ({str(e)[:60]})")

        with _lock:
            job.status = "composing"

        # ── WIREFRAME: the pieces, positioned on a plain canvas ──
        proof = jdir / f"{vid}_layout.png"
        # ── readability judgement of the wireframe (before fill) — flag pieces
        #    that won't read; remedy = text colour or background field colour ──
        for n in edits.judge_wireframe(brief):
            _log(job, f"{vid}: {n}")

        _log(job, f"{vid}: wireframe — {len(brief.placements)} pieces on the blank canvas")
        render_layout(brief, proof, brand_id=bid, mode="proof")
        _trail(
            job,
            "layout",
            f"{vid.split('_')[-1]}: wireframe ready",
            vid,
            str(proof),
            notes=[f"{p.kind}:{p.role}" for p in brief.placements],
        )

        # ── FILL: the image model paints the whole background from the wireframe ──
        bg = jdir / f"{vid}_bg.png"
        _log(job, f"{vid}: painting background from wireframe — bg_story: {(brief.bg_story or '')[:60]}")
        def capture_fill_request(prompt: str, reference: str) -> None:
            variant.fill_prompt = prompt
            variant.ref_image = reference
            variant.layout_image = reference
            variant.fill_model = (
                config.FAL_IMAGE_MODEL
                if config.IMAGE_BACKEND == "fal"
                else config.CF_I2I_MODEL
                if config.IMAGE_BACKEND == "cloudflare"
                else config.IMAGE_MODEL
            )

        try:
            _, f_prompt, f_ref = fill_background(
                brief, bg, brand_id=bid, workdir=jdir, on_prepared=capture_fill_request
            )
            variant.fill_prompt = f_prompt
            variant.ref_image = f_ref
            variant.fill_error = ""
        except Exception as e:
            variant.fill_error = str(e)[:500]
            _log(job, f"{vid}: fill failed ({str(e)[:80]}) — flat field fallback")
            from .layout.canvas import _brief_size, _field_fill, _rect_px
            from PIL import Image, ImageDraw

            W, H = _brief_size(brief)
            im = Image.new("RGB", (W, H), (255, 255, 255))
            d = ImageDraw.Draw(im)
            for f in brief.bg_fields or []:
                x, y, w, h = _rect_px(f.rect, W, H)
                d.rectangle([x, y, x + w, y + h], fill=_field_fill(f))
            im.save(bg)

        # ── composite: generated image at the bottom, real pieces on top ──
        img = jdir / f"{vid}_design.png"
        render_composite(str(bg), brief, img, brand_id=bid)
        # ── post-fill readability: the fill model may miss field colours — the
        #    vision judge looks at the REAL composite and applies the smallest
        #    ink/container remedy (background targets flip piece ink — there is
        #    no second fill in the generation flow) ──
        try:
            mdict = build_manifest(bid, job.id, vid, str(bg), brief).model_dump()
            palette_hex = [p.get("hex") for p in (grammar.palette or []) if p.get("hex")]
            flags = edits.judge_readability(str(img), mdict, allow_bg=False, palette=palette_hex)
            if flags:
                mdict, notes, _ = edits.apply_readability(mdict, flags)
                by_role = {p.role: p for p in brief.placements}
                for l in mdict.get("layers", []):
                    p = by_role.get(l.get("role") or "")
                    if not p:
                        continue
                    st = dict(p.style or {})
                    lst = l.get("style") or {}
                    if l.get("type") == "text" and lst.get("color"):
                        st["color"] = lst["color"]
                    elif l.get("type") == "shape":
                        if lst.get("fill"):
                            st["fill"] = lst["fill"]
                        if lst.get("stroke") is not None:
                            st["stroke"] = lst["stroke"]
                    p.style = st
                for n in notes:
                    _log(job, f"{vid}: {n}")
                render_composite(str(bg), brief, img, brand_id=bid)
        except Exception as e:
            _log(job, f"{vid}: readability judge skipped ({str(e)[:60]})")
        variant.image = str(img)
        variant.history = [str(bg)]
        _trail(
            job,
            "compose",
            f"{vid.split('_')[-1]}: background painted + pieces placed ({cohort.name})",
            vid,
            str(img),
            notes=[cohort.idea[:64], brief.copy.headline],
        )
        variant.reports = []
        variant.best_report = None
        variant.status = "done"
        with _lock:
            store.save_job(bid, job)
        return variant

    # parallel layout+fill — publish each variant the moment it lands
    with ThreadPoolExecutor(max_workers=max(1, n_var)) as pool:
        futs = {pool.submit(run_variant, i, c): i for i, c in enumerate(cohorts)}
        done_map: dict[int, Variant] = {}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                done_map[i] = fut.result()
            except Exception as e:
                _log(job, f"v{i + 1} failed: " + " | ".join(traceback.format_exc().strip().splitlines()[-3:])[:300])
                done_map[i] = Variant(id=f"{job.id}_v{i + 1}", status="failed", prompt=str(e))
            with _lock:
                job.variants = [done_map[k] for k in sorted(done_map)]
                store.save_job(bid, job)

    variants = [done_map[k] for k in sorted(done_map)]
    job.variants = variants
    ok = [v for v in variants if v.image and v.brief and v.brief.placements]
    if not ok:
        job.status = "failed"
        job.error = "all variants failed to compose"
        store.save_job(bid, job)
        return job

    job.status = "selecting"
    winner = max(ok, key=lambda v: len(v.brief.placements)) if ok else None
    job.selected = winner.id
    _log(job, f"selected {winner.id}")
    _trail(job, "select", f"winner: {winner.brief.story[:48] if winner.brief else winner.id}", winner.id, winner.image)

    # ── MANIFEST: bg raster + live layers — built instantly, nothing to strip ──
    job.status = "delivering"
    bg = winner.history[0] if winner.history else str(jdir / f"{winner.id}_bg.png")
    manifest = build_manifest(bid, job.id, winner.id, bg, winner.brief)
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
            notes=[f"winner {winner.id}", f"score {winner.best_report.score if winner.best_report else ''}", f"{len(manifest.layers)} layers (bg + pieces — separated)"],
        )
    ]
    job.status = "done"
    _log(job, f"done in {time.time() - t0:.1f}s — background + {len(manifest.layers) - 1} live layers, no strip needed")
    _trail(job, "manifest", f"editable canvas: {len(manifest.layers)} layers", winner.id, winner.image, notes=[f"{l.type}:{l.role}" for l in manifest.layers])
    with _lock:
        store.save_job(bid, job)
    return job


def finalize_job(brand_id: str, job_id: str, force: bool = False):
    """(compat) the manifest is built inline now — rebuild only if missing."""
    with _flock(f"{brand_id}:{job_id}"):
        job = store.load_job(brand_id, job_id)
        if not job:
            return
        if job.status not in ("done", "failed"):
            return  # a run is live — never clobber its state with a stale snapshot
        gen = next((e for e in job.edits if e.id == "generated"), None)
        if gen and gen.manifest and Path(gen.manifest).exists() and not force:
            return
        winner = next((v for v in job.variants if v.id == job.selected), None) or (job.variants[0] if job.variants else None)
        if not winner or not winner.image or not winner.brief:
            return
        jdir = store.job_dir(brand_id, job.id)
        bg = winner.history[0] if winner.history else str(jdir / f"{winner.id}_bg.png")
        if not Path(bg).exists():
            bg = winner.image
        manifest = build_manifest(brand_id, job.id, winner.id, bg, winner.brief)
        manifest_path = jdir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2))
        if gen:
            gen.manifest = str(manifest_path)
        else:
            job.edits.insert(
                0,
                EditDraft(
                    id="generated",
                    parent="",
                    instruction=job.use_case,
                    kind="generate",
                    image=winner.image,
                    manifest=str(manifest_path),
                    status="done",
                    created=time.time(),
                ),
            )
        with _lock:
            store.save_job(brand_id, job)


def ensure_finalized(brand_id: str, job_id: str) -> None:
    """Make the editable canvas ready (compat no-op when the manifest exists)."""
    job = store.load_job(brand_id, job_id)
    if not job:
        return
    gen = next((e for e in job.edits if e.id == "generated"), None)
    if gen and gen.manifest and Path(gen.manifest).exists():
        return
    finalize_job(brand_id, job_id)


def run_full(brand_id: str, use_case: str, ratio: str = "1:1", folder: str = "") -> Job:
    job = create_job(brand_id, use_case, ratio, folder=folder)
    return run_job(job.id, brand_id, ratio)
