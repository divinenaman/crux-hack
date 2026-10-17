import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, edits, flow, store
from .models import EditDraft

app = FastAPI(title="Crux Agentic Image Editor")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=str(config.WORKSPACE)), name="files")


class BrandReq(BaseModel):
    id: str
    name: str = ""


class IngestReq(BaseModel):
    root: str = ""


class JobReq(BaseModel):
    use_case: str
    ratio: str = "1:1"
    variants: int = 4
    folder: str = ""


class EditReq(BaseModel):
    parent: str = ""
    instruction: str


class RunReq(BaseModel):
    ratio: str = ""


@app.get("/api/health")
def health():
    store.ensure_migrated()
    brands = store.list_brands()
    return {
        "ok": True,
        "brands": [b.id for b in brands],
        "agent_thinking": "deepseek-pro",
        "agent_vision": "deepseek-flash",
        "image_model": config.IMAGE_MODEL,
    }


@app.get("/api/brands")
def brands():
    out = []
    for b in store.list_brands():
        d = b.model_dump()
        d["assets"] = len(store.load_catalog(b.id))
        d["jobs"] = len(store.list_jobs(b.id))
        out.append(d)
    return out


@app.post("/api/brands")
def create_brand(req: BrandReq):
    bid = "".join(c if c.isalnum() or c in "_-" else "_" for c in req.id.lower())[:32]
    if not bid:
        raise HTTPException(400, "bad id")
    b = store.create_brand(bid, req.name or bid)
    return b.model_dump()


@app.get("/api/brands/{brand_id}")
def get_brand(brand_id: str):
    b = store.get_brand(brand_id)
    if not b:
        raise HTTPException(404, "brand not found")
    d = b.model_dump()
    d["assets"] = len(store.load_catalog(brand_id))
    d["jobs"] = store.list_jobs(brand_id)
    d["tree"] = store.folder_tree(brand_id)
    g = store.load_grammar(brand_id)
    d["rules"] = {
        "brand": g.brand,
        "palette": g.palette,
        "context_rules": [r.model_dump() for r in g.context_rules],
        "techniques": [t.model_dump() for t in g.techniques],
        "logo_rules": g.logo_rules,
        "safe_zones": g.safe_zones,
        "donts": g.donts,
    }
    return d


@app.post("/api/brands/{brand_id}/ingest")
def ingest(brand_id: str, req: IngestReq):
    if not store.get_brand(brand_id):
        store.create_brand(brand_id)
    root = req.root or store.get_brand(brand_id).source_root or str(config.ROOT / "Brand Kit")
    return flow.ingest(brand_id, root)


@app.get("/api/brands/{brand_id}/tree")
def tree(brand_id: str):
    return store.folder_tree(brand_id)


@app.get("/api/brands/{brand_id}/assets")
def assets(
    brand_id: str,
    folder: str = "",
    q: str = "",
    kind: str = "",
    color: str = "",
    use_case: str = "",
    mismatch: int = 0,
):
    out = store.query_assets(brand_id, folder=folder, q=q, kind=kind, color=color, use_case=use_case, mismatch=bool(mismatch))
    return [a.model_dump() for a in out]


@app.get("/api/brands/{brand_id}/rules")
def rules(brand_id: str):
    g = store.load_grammar(brand_id)
    return g.model_dump()


@app.get("/api/brands/{brand_id}/jobs")
def jobs(brand_id: str):
    return store.list_jobs(brand_id)


def _run_safe(job_id: str, brand_id: str, ratio: str):
    try:
        flow.run_job(job_id, brand_id, ratio or None)
    except Exception as e:
        job = store.load_job(brand_id, job_id)
        if job:
            job.status = "failed"
            job.error = str(e)
            job.log.append(f"error: {e}")
            store.save_job(brand_id, job)


@app.post("/api/brands/{brand_id}/jobs")
def create_job(brand_id: str, req: JobReq):
    if not store.get_brand(brand_id):
        raise HTTPException(404, "brand not found")
    job = flow.create_job(brand_id, req.use_case, req.ratio, req.variants, req.folder)
    threading.Thread(target=_run_safe, args=(job.id, brand_id, req.ratio), daemon=True).start()
    return job.model_dump(by_alias=True)


@app.post("/api/brands/{brand_id}/jobs/{job_id}/run")
def run_job(brand_id: str, job_id: str, req: RunReq | None = None):
    if not store.load_job(brand_id, job_id):
        raise HTTPException(404, "not found")
    threading.Thread(target=_run_safe, args=(job_id, brand_id, req.ratio if req else ""), daemon=True).start()
    return {"ok": True, "id": job_id}


@app.get("/api/brands/{brand_id}/jobs/{job_id}")
def get_job(brand_id: str, job_id: str):
    job = store.load_job(brand_id, job_id)
    if not job:
        raise HTTPException(404, "not found")
    _ensure_generated(brand_id, job)
    return job.model_dump(by_alias=True)


def _manifest_path(brand_id: str, job_id: str, draft: str) -> Path:
    jdir = store.job_dir(brand_id, job_id)
    if draft in ("", "generated"):
        return jdir / "manifest.json"
    return jdir / "edits" / draft / "manifest.json"


def _ensure_generated(brand_id: str, job) -> None:
    """Backfill a 'generated' root draft on old jobs so they stay editable."""
    if any(e.id == "generated" for e in job.edits):
        return
    mpath = _manifest_path(brand_id, job.id, "generated")
    if not mpath.exists():
        return
    sel = next((v for v in job.variants if v.id == job.selected), None)
    image = (sel.image if sel else "") or ""
    try:
        data = json.loads(mpath.read_text())
        image = data.get("design_src") or image
    except Exception:
        pass
    job.edits.insert(
        0,
        EditDraft(
            id="generated",
            parent="",
            instruction=job.use_case,
            kind="generate",
            image=image,
            manifest=str(mpath),
            status="done",
            created=time.time(),
            notes=["backfilled editable canvas"],
        ),
    )
    store.save_job(brand_id, job)


@app.get("/api/brands/{brand_id}/jobs/{job_id}/manifest")
def get_manifest(brand_id: str, job_id: str, draft: str = "generated"):
    p = _manifest_path(brand_id, job_id, draft)
    if not p.exists():
        raise HTTPException(404, "manifest not ready")
    return FileResponse(p)


@app.get("/api/brands/{brand_id}/jobs/{job_id}/edits/{edit_id}")
def get_edit(brand_id: str, job_id: str, edit_id: str):
    job = store.load_job(brand_id, job_id)
    if not job:
        raise HTTPException(404, "not found")
    for e in job.edits:
        if e.id == edit_id:
            return e.model_dump()
    raise HTTPException(404, "edit not found")


def _edit_safe(brand_id: str, job_id: str, parent: str, instruction: str):
    try:
        create_edit_draft(brand_id, job_id, parent, instruction)
    except Exception as e:
        job = store.load_job(brand_id, job_id)
        if job:
            for e_ in job.edits:
                if e_.status == "running":
                    e_.status = "failed"
                    e_.notes = [str(e)]
            job.status = "done"
            job.error = f"edit failed: {e}"
            job.log.append(f"edit error: {e}")
            store.save_job(brand_id, job)


@app.post("/api/brands/{brand_id}/jobs/{job_id}/edits")
def post_edit(brand_id: str, job_id: str, req: EditReq):
    job = store.load_job(brand_id, job_id)
    if not job:
        raise HTTPException(404, "not found")
    if job.status != "done":
        raise HTTPException(400, "job not finished")
    threading.Thread(target=_edit_safe, args=(brand_id, job_id, req.parent, req.instruction), daemon=True).start()
    return {"ok": True}


def create_edit_draft(brand_id: str, job_id: str, parent: str, instruction: str):
    job = store.load_job(brand_id, job_id)
    if not job:
        raise ValueError("job not found")
    parent = parent or "generated"
    _ensure_generated(brand_id, job)
    parent_draft = next((e for e in job.edits if e.id == parent), None)
    if not parent_draft:
        raise ValueError(f"parent draft '{parent}' not found")

    n = sum(1 for e in job.edits if e.id.startswith("edit-")) + 1
    edit_id = f"edit-{n}"
    edir = store.job_dir(brand_id, job_id) / "edits" / edit_id
    edir.mkdir(parents=True, exist_ok=True)

    draft = EditDraft(
        id=edit_id,
        parent=parent,
        instruction=instruction,
        status="running",
        created=time.time(),
    )
    job.edits.append(draft)
    job.status = "editing"
    store.save_job(brand_id, job)

    manifest = edits.load_manifest(parent_draft.manifest)
    plan = edits.classify_edit(instruction, manifest)
    draft.kind = plan.get("kind", "visual")

    new_manifest = dict(manifest)
    new_manifest["layers"] = [dict(l) for l in manifest.get("layers", [])]

    image = parent_draft.image
    if draft.kind in ("visual", "both"):
        out = edir / "design.png"
        image = edits.apply_visual_edit(new_manifest, edits.design_path_of(manifest) or parent_draft.image, out, plan.get("visual_prompt") or instruction, plan.get("rects") or [])
        new_manifest["design_src"] = image
        for l in new_manifest["layers"]:
            if l.get("role") == "design":
                l["src"] = image
        draft.notes.append(f"visual: {(plan.get('visual_prompt') or '')[:80]}")
    if draft.kind in ("text", "both"):
        new_manifest = edits.apply_text_changes(new_manifest, plan.get("text_changes") or [])
        draft.notes.append("text: " + ", ".join(f"{c.get('role')}→'{str(c.get('content'))[:24]}'" for c in (plan.get("text_changes") or [])))

    mpath = edir / "manifest.json"
    edits.save_manifest(mpath, new_manifest)
    draft.image = image
    draft.manifest = str(mpath)
    draft.status = "done"
    job.status = "done"
    job.error = ""
    store.save_job(brand_id, job)
    return draft


@app.get("/api/brands/{brand_id}/refs/{asset_id}")
def get_asset_file(brand_id: str, asset_id: str):
    asset = store.get_asset(brand_id, asset_id)
    if not asset or not Path(asset.png).exists():
        raise HTTPException(404, "asset not found")
    return FileResponse(asset.png)
