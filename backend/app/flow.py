from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, store
from .brief.cohorts import plan_cohorts
from .brief.contact import build_contact_sheet
from .brief.shortlist import validate_affinity
from .compose.composer import apply_fix, compose, parse_frac_rects, strip_text_and_logo
from .fidelity.manifest import build_manifest
from .fidelity.textfit import apply_measured, mark_replaceable, measure_overlays, replacement_plan
from .ingest.pipeline import run_ingest
from .judge.critic import judge, verify_strip
from .judge.layout_tune import tune_placement
from .models import Brief, Cohort, EditDraft, Job, TrailItem, Variant

_lock = threading.Lock()


def _log(job: Job, msg: str):
    with _lock:
        job.log.append(msg)
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


def ingest(brand_id: str, root: str) -> dict:
    return run_ingest(brand_id, root)


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
    job = Job(
        id=f"job_{Path(use_case).stem[:24].replace(' ', '_')}_{store.load_catalog(brand_id).__len__()}_{int(time.time())}",
        brand_id=brand_id,
        folder=folder,
        use_case=use_case,
        ratio=ratio,
        n_variants=max(1, min(6, n_variants)),
    )
    job.id = "".join(c if c.isalnum() or c in "_-" else "_" for c in job.id)[:64]
    store.save_job(brand_id, job)
    return job


def run_job(job_id: str, brand_id: str | None = None, ratio: str | None = None) -> Job:
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
    store.save_job(bid, job)
    n_var = max(1, min(6, job.n_variants or 4))
    _log(job, f"planning {n_var} idea cohorts (thinking model, folder='{job.folder or 'all'}')")
    _trail(job, "brief", f"planning {n_var} distinct idea cohorts")
    cohorts = plan_cohorts(bid, job.use_case, grammar, n=n_var, folder=job.folder)
    _trail(
        job,
        "brief",
        "cohort stories + asset sets locked",
        notes=[f"{c.name} [{c.angle}]: {c.story[:56]}" for c in cohorts],
    )

    def run_variant(i: int, cohort: Cohort) -> Variant:
        vid = f"{job.id}_v{i+1}"
        variant = Variant(id=vid, prompt=f"{cohort.angle} | {cohort.name}")
        brief = _cohort_to_brief(job, cohort)

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
            f"{vid.split('_')[-1]}: cohort {len(brief.slots)} assets · {brief.color_story[:40]}",
            vid,
            str(contact),
            notes=[f"{s.role}→{s.asset_id}: {s.why[:48]}" for s in brief.slots],
        )

        with _lock:
            job.status = "composing"
        _log(job, f"{vid}: composing — idea: {cohort.idea[:60]}")
        img = jdir / f"{vid}_design.png"
        compose(brief, grammar, str(contact), img, refs, brand_id=bid)
        variant.brief = brief
        variant.image = str(img)
        _trail(
            job,
            "compose",
            f"{vid.split('_')[-1]}: first design ({cohort.name})",
            vid,
            str(img),
            notes=[cohort.idea[:64], brief.copy.headline],
        )

        with _lock:
            job.status = "judging"
        variant.status = "judging"

        best_score, best_path = -1.0, str(img)
        current = img
        prev_score = None
        for rnd in range(config.MAX_JUDGE_ROUNDS):
            _log(job, f"{vid}: judge round {rnd + 1}")
            report = judge(str(current), brief, grammar, brand_id=bid)
            variant.reports.append(report)
            fails = [i.check for i in report.items if not i.pass_]
            _log(job, f"{vid}: score {report.score} fails={fails}")
            _trail(
                job,
                "judge",
                f"{vid.split('_')[-1]}: judge round {rnd + 1}",
                vid,
                str(current),
                score=report.score,
                notes=[f"{i.check}: {i.note[:56]}" for i in report.items if not i.pass_],
            )
            if report.score > best_score:
                best_score = report.score
                best_path = str(current)
            last = rnd == config.MAX_JUDGE_ROUNDS - 1
            stagnant = prev_score is not None and report.score <= prev_score
            if report.score >= 92 or not report.fixes or last or stagnant:
                break
            prev_score = report.score
            variant.status = "fixing"
            with _lock:
                job.status = "fixing"
            _log(job, f"{vid}: fixing — {report.fixes[0][:80]}")
            nxt = jdir / f"{vid}_fix{rnd + 1}.png"
            apply_fix(brief, current, nxt, report.fixes[0])
            current = nxt
            variant.history.append(str(nxt))
            _trail(job, "fix", f"{vid.split('_')[-1]}: fix {rnd + 1}", vid, str(nxt), notes=[report.fixes[0][:72]])

        variant.image = best_path
        variant.best_report = max(variant.reports, key=lambda r: r.score) if variant.reports else None
        variant.status = "done"
        _log(job, f"{vid}: done best_score={best_score}")
        _trail(job, "variant", f"{vid.split('_')[-1]}: best output", vid, best_path, score=best_score)
        return variant

    with ThreadPoolExecutor(max_workers=max(1, n_var)) as pool:
        variants = list(pool.map(lambda ic: run_variant(*ic), list(enumerate(cohorts))))

    job.variants = variants
    job.status = "selecting"
    winner = max(variants, key=lambda v: (v.best_report.score if v.best_report else 0))
    job.selected = winner.id
    _log(job, f"selected {winner.id}")
    _trail(job, "select", f"winner: {winner.brief.story[:48]}", winner.id, winner.image, score=winner.best_report.score if winner.best_report else None)

    job.status = "delivering"
    assert winner.brief is not None
    typo = grammar.typography or {}
    font_hint = typo.get("headline_font") or typo.get("body_font") or ""
    plan = replacement_plan(winner.brief, bid, font_hint)
    winner.brief = mark_replaceable(winner.brief, plan)
    _log(job, "replacement plan: " + ", ".join(f"{r}={'REPLACE' if p['replace'] else 'keep baked'} [{p['reason']}]" for r, p in plan.items()))
    _log(job, "measuring baked text/logo pixels (vision windows + deterministic CV)")
    measured = measure_overlays(str(winner.image), winner.brief, font_hint=font_hint)
    if measured:
        winner.brief = apply_measured(winner.brief, measured)
    else:
        _log(job, "measurement empty — falling back to vision placement tune")
        winner.brief = tune_placement(str(winner.image), winner.brief)
    _trail(
        job,
        "tune",
        f"placement locked to measured pixels ({len(measured)} overlays: exact pos/size/colour)",
        winner.id,
        str(winner.image),
        notes=[f"{r}: {[round(v, 3) for v in m['bbox']]}" for r, m in measured.items()],
    )

    stripped = jdir / f"{winner.id}_stripped.png"
    _log(job, "stripping baked text/logo (masked, exact strings)")
    strip_text_and_logo(winner.brief, Path(winner.image), stripped)
    _trail(job, "strip", "removed exact text + logo (become live layers)", winner.id, str(stripped), notes=[z.content or z.role for z in winner.brief.zones])

    for attempt in range(3):
        clean, leftovers = verify_strip(str(stripped), winner.brief)
        if clean:
            break
        _log(job, f"strip verify: {len(leftovers)} leftovers — re-stripping")
        joined = "; ".join(leftovers[:4])
        extra_rects = parse_frac_rects(joined)
        nxt = jdir / f"{winner.id}_strip{attempt + 2}.png"
        strip_text_and_logo(winner.brief, Path(stripped), nxt, extra_rects=extra_rects, extra_notes=joined)
        stripped = nxt
        _trail(job, "strip", f"re-strip round {attempt + 2}", winner.id, str(stripped), notes=leftovers[:3])

    manifest = build_manifest(bid, job.id, winner.id, str(stripped), winner.brief)
    winner.manifest = manifest
    manifest_path = jdir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2))
    job.status = "done"
    job.edits = [
        EditDraft(
            id="generated",
            parent="",
            instruction=job.use_case,
            kind="generate",
            image=str(stripped),
            manifest=str(manifest_path),
            status="done",
            created=time.time(),
            notes=[f"winner {winner.id}", f"score {winner.best_report.score if winner.best_report else ''}"],
        )
    ]
    _log(job, "manifest written — design stripped, text/logo as layers; click Edit to iterate")
    _trail(job, "manifest", f"editable canvas: {len(manifest.layers)} layers", winner.id, str(stripped), notes=[f"{l.type}:{l.role}" for l in manifest.layers])
    store.save_job(bid, job)
    return job


def run_full(brand_id: str, use_case: str, ratio: str = "1:1", folder: str = "") -> Job:
    job = create_job(brand_id, use_case, ratio, folder=folder)
    return run_job(job.id, brand_id, ratio)
