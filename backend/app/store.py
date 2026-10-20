import json
import shutil
import threading
import time
from typing import Optional

from . import config
from .models import Asset, Brand, Grammar, Job

_lock = threading.RLock()
_migrated = False


def _read_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def ensure_migrated():
    global _migrated
    with _lock:
        if _migrated:
            return
        _migrated = True
        target = config.brand_dir("xero")
        if (target / "catalog.json").exists():
            _migrate_classification()
            return
        if config.CATALOG_PATH.exists():
            shutil.copy(config.CATALOG_PATH, target / "catalog.json")
        if config.GRAMMAR_PATH.exists():
            shutil.copy(config.GRAMMAR_PATH, target / "grammar" / "grammar.json")
        if config.LEGACY_JOBS_DIR.exists():
            for p in config.LEGACY_JOBS_DIR.iterdir():
                dest = config.brand_jobs_dir("xero") / p.name
                if not dest.exists():
                    if p.is_dir():
                        shutil.copytree(p, dest)
                    else:
                        shutil.copy(p, dest)
        save_brand(Brand(id="xero", name="Xero", created=time.time(), source_root=str(config.ROOT / "Brand Kit")))
        _migrate_classification()


def _migrate_classification():
    """Stamp element|reference + colourway groups on existing catalogs (idempotent)."""
    from .ingest import groups

    for b in list_brands():
        try:
            catalog = load_catalog(b.id)
            if not catalog:
                continue
            grammar = load_grammar(b.id)
            groups.enrich_classification(catalog, grammar)
            grammar.palette_refs = groups.pick_palette_refs(catalog, grammar)
            save_catalog(b.id, catalog)
            save_grammar(b.id, grammar)
        except Exception:
            continue


def list_brands() -> list[Brand]:
    ensure_migrated()
    with _lock:
        out = []
        for p in sorted(config.BRANDS_DIR.iterdir()) if config.BRANDS_DIR.exists() else []:
            if not p.is_dir():
                continue
            meta = _read_json(p / "brand.json", {"id": p.name, "name": p.name})
            out.append(Brand.model_validate(meta))
        return out


def get_brand(brand_id: str) -> Optional[Brand]:
    ensure_migrated()
    with _lock:
        p = config.brand_dir(brand_id) / "brand.json"
        if not p.exists():
            if (config.brand_catalog_path(brand_id)).exists():
                return Brand(id=brand_id, name=brand_id)
            return None
        return Brand.model_validate(_read_json(p, {"id": brand_id}))


def save_brand(brand: Brand):
    with _lock:
        _write_json(config.brand_dir(brand.id) / "brand.json", brand.model_dump())


def create_brand(brand_id: str, name: str = "", source_root: str = "") -> Brand:
    b = Brand(id=brand_id, name=name or brand_id, created=time.time(), source_root=source_root)
    save_brand(b)
    return b


def load_catalog(brand_id: str) -> list[Asset]:
    ensure_migrated()
    with _lock:
        return [Asset.model_validate(a) for a in _read_json(config.brand_catalog_path(brand_id), [])]


def save_catalog(brand_id: str, assets: list[Asset]):
    with _lock:
        _write_json(config.brand_catalog_path(brand_id), [a.model_dump() for a in assets])


def upsert_assets(brand_id: str, new_assets: list[Asset]) -> list[Asset]:
    with _lock:
        catalog = {a.id: a for a in load_catalog(brand_id)}
        for a in new_assets:
            catalog[a.id] = a
        out = list(catalog.values())
        save_catalog(brand_id, out)
        return out


def get_asset(brand_id: str, asset_id: str) -> Optional[Asset]:
    assets = load_catalog(brand_id)
    for a in assets:
        if a.id == asset_id:
            return a
    for a in assets:  # tolerate decorated ids (e.g. "..._Blooms" suffix)
        if asset_id.startswith(a.id):
            return a
    return None


def load_grammar(brand_id: str) -> Grammar:
    ensure_migrated()
    with _lock:
        raw = _read_json(config.brand_grammar_path(brand_id), None)
        if not raw:
            return Grammar()
        return Grammar.model_validate(raw)


def save_grammar(brand_id: str, grammar: Grammar):
    with _lock:
        _write_json(config.brand_grammar_path(brand_id), grammar.model_dump())


def save_job(brand_id: str, job: Job):
    with _lock:
        path = config.brand_jobs_dir(brand_id) / f"{job.id}.json"
        _write_json(path, job.model_dump(by_alias=True))


def load_job(brand_id: str, job_id: str) -> Optional[Job]:
    ensure_migrated()
    with _lock:
        path = config.brand_jobs_dir(brand_id) / f"{job_id}.json"
        if not path.exists():
            return None
        return Job.model_validate(_read_json(path, {}))


def find_job(job_id: str) -> Optional[tuple[str, Job]]:
    for b in list_brands():
        job = load_job(b.id, job_id)
        if job:
            return b.id, job
    return None


def list_jobs(brand_id: str) -> list[dict]:
    with _lock:
        out = []
        d = config.brand_jobs_dir(brand_id)
        for p in d.glob("*.json"):
            raw = _read_json(p, {})
            variants = raw.get("variants") or []
            sel = raw.get("selected") or ""
            image = next((v.get("image") for v in variants if v.get("id") == sel and v.get("image")), "")
            if not image:
                image = next((v.get("image") for v in variants if v.get("image")), "")
            out.append(
                {
                    "id": raw.get("id"),
                    "use_case": raw.get("use_case"),
                    "status": raw.get("status"),
                    "selected": sel,
                    "folder": raw.get("folder"),
                    "brand_id": raw.get("brand_id"),
                    "ratio": raw.get("ratio"),
                    "n_variants": len(variants),
                    "n_edits": len(raw.get("edits") or []),
                    "image": image,
                    "error": raw.get("error") or "",
                }
            )
        out.sort(key=lambda j: _job_ts(str(j.get("id") or "")), reverse=True)
        return out


def _job_ts(job_id: str) -> float:
    tail = job_id.rsplit("_", 1)[-1]
    try:
        return float(tail)
    except ValueError:
        return 0.0


def job_dir(brand_id: str, job_id: str):
    d = config.brand_jobs_dir(brand_id) / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def query_assets(
    brand_id: str,
    folder: str = "",
    q: str = "",
    kind: str = "",
    color: str = "",
    use_case: str = "",
    mismatch: bool = False,
) -> list[Asset]:
    out = load_catalog(brand_id)
    if folder:
        out = [a for a in out if a.folder == folder or a.folder.startswith(folder.rstrip("/") + "/")]
    if kind:
        out = [a for a in out if a.kind == kind]
    if color:
        c = color.lower()
        out = [a for a in out if any(c in x.lower() for x in a.colors)]
    if use_case:
        u = use_case.lower()
        out = [a for a in out if any(u in x.lower() for x in a.use_cases) or u in a.semantic.lower()]
    if mismatch:
        out = [a for a in out if a.mismatches]
    if q:
        ql = q.lower()
        out = [
            a
            for a in out
            if ql in a.name.lower()
            or ql in a.semantic.lower()
            or any(ql in t.lower() for t in a.tags)
            or any(ql in t.lower() for t in a.use_cases)
            or ql in a.folder.lower()
        ]
    return out


def folder_tree(brand_id: str) -> list[dict]:
    counts: dict[str, int] = {}
    for a in load_catalog(brand_id):
        counts[a.folder or "."] = counts.get(a.folder or ".", 0) + 1
    nodes: dict[str, dict] = {}
    roots: list[dict] = []
    for folder in sorted(counts):
        parts = [] if folder in (".", "") else folder.split("/")
        path = ""
        parent = None
        for i, part in enumerate(parts):
            path = f"{path}/{part}" if path else part
            if path not in nodes:
                node = {"path": path, "name": part, "count": 0, "children": []}
                nodes[path] = node
                if parent is None:
                    roots.append(node)
                else:
                    parent["children"].append(node)
            parent = nodes[path]
        if parent is not None:
            parent["count"] += counts[folder]
        else:
            roots.append({"path": ".", "name": "(root)", "count": counts[folder], "children": []})
    return roots
