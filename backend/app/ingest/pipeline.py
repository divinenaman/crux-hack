import re
import uuid
from pathlib import Path

from .. import config, store
from ..imutil import ensure_raster
from ..models import Asset, Grammar
from . import classify, fonts, grid, quality
from .grammar import extract_grammar_pages

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def _sid(*parts: str) -> str:
    raw = "_".join(parts)
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:80] or uuid.uuid4().hex[:8]


def _folder_of(p: Path, root: Path) -> str:
    try:
        rel = p.parent.relative_to(root)
        s = str(rel).replace("\\", "/")
        return "" if s == "." else s
    except ValueError:
        return p.parent.name


def _svg_asset(path: Path, root: Path, brand_id: str) -> Asset:
    asset_id = _sid(path.parent.name, path.stem)
    raster = config.brand_assets_dir(brand_id) / f"{asset_id}.png"
    try:
        png = ensure_raster(path, raster)
    except Exception:
        png = ""
    return Asset(
        id=asset_id,
        name=path.stem,
        kind="vector",
        tags=["illustration", "vector"],
        usage="Use as-is, preserves vector fidelity.",
        role_hints=["illustration", "accent"],
        png=png,
        source=str(path),
        directly_usable=bool(png),
        exact_required=True,
        brand_id=brand_id,
        folder=_folder_of(path, root),
    )


def _is_doc_page(p: Path) -> bool:
    folder = p.parent.name.lower()
    if "guidelines" in folder or "safe_zone" in folder or "safe zone" in folder:
        return True
    return bool(re.match(r"\d{2}_\d{2}_", p.name.lower()))


def run_ingest(brand_id: str, root: str, on_log=None) -> dict:
    root_p = Path(root)
    files = sorted(p for p in root_p.rglob("*") if p.suffix.lower() in IMG_EXTS)
    log = on_log or (lambda m: None)
    log(f"found {len(files)} images under {root_p.name}")

    new_assets: list[Asset] = []
    doc_pages: list[str] = []
    singles: list[Path] = []
    chapter_sheets: list[Path] = []

    for p in files:
        if p.suffix.lower() == ".svg":
            new_assets.append(_svg_asset(p, root_p, brand_id))
            continue
        if _is_doc_page(p):
            doc_pages.append(str(p))
            if re.match(r"\d{2}_\d{2}_", p.name.lower()):
                chapter_sheets.append(p)
            continue
        singles.append(p)

    log(f"doc pages: {len(doc_pages)}, singles: {len(singles)}")

    if doc_pages:
        log("extracting grammar (brand rules) from doc pages")
        g: Grammar = extract_grammar_pages(doc_pages, store.load_grammar(brand_id))
        log("identifying brand typography (font identification step)")
        typo = fonts.identify_fonts(doc_pages)
        if typo.get("headline_font") or typo.get("body_font"):
            merged = dict(g.typography or {})
            merged.update({k: v for k, v in typo.items() if v and k != "weights"})
            if typo.get("weights"):
                merged["weights"] = ", ".join(typo["weights"])
            g.typography = merged
            for fam in (typo.get("headline_font"), typo.get("body_font")):
                hit = fonts.ensure_font_file(fam)
                log(f"font '{fam}' -> {hit or 'not found (fallback will be used)'}")
        else:
            log("font identification: no typography found on doc pages")
        store.save_grammar(brand_id, g)
        log(f"grammar: {len(g.lexicon)} lexicon, {len(g.recipes)} recipes, {len(g.techniques)} techniques, {len(g.context_rules)} rules")

    assets_dir = config.brand_assets_dir(brand_id)

    for sheet in chapter_sheets:
        cells = grid.crop_cells(sheet, assets_dir / f"{_sid(sheet.parent.name, sheet.stem)}_cells", _sid(sheet.parent.name, sheet.stem))
        if len(cells) < 3:
            continue
        log(f"grid-cropping composite sheet {sheet.name} -> {len(cells)} individual assets")
        names = classify.name_cells(str(sheet), [c["png"] for c in cells])
        for c in cells:
            meta = names.get(c["name"], {})
            new_assets.append(
                Asset(
                    id=c["name"],
                    name=classify._as_str(meta.get("name", c["name"])),
                    kind="bloom",
                    tags=classify._as_list(meta.get("tags", ["shape"])),
                    semantic=classify._as_str(meta.get("semantic", "")),
                    usage="Exact grid-cell crop from brand lexicon sheet.",
                    role_hints=["bloom", "accent", "mask"],
                    png=c["png"],
                    source=str(sheet),
                    bbox=c["bbox"],
                    directly_usable=True,
                    brand_id=brand_id,
                    folder=_folder_of(sheet, root_p),
                )
            )

    batch = [str(p) for p in singles]
    items: list[dict] = []
    for i in range(0, len(batch), 8):
        chunk = batch[i : i + 8]
        log(f"classifying {i}..{i + len(chunk)} of {len(batch)}")
        items += classify.classify_batch(chunk, str(root_p))

    by_file = {it.get("file", ""): it for it in items}
    for p in singles:
        it = by_file.get(p.name) or {}
        if not it:
            it = {"file": p.name, "kind": "single", "name": p.stem}
        asset_id = _sid(p.parent.name, p.stem)
        dest = assets_dir / f"{asset_id}{p.suffix.lower()}"
        if not dest.exists():
            dest.write_bytes(p.read_bytes())
        a = classify.item_to_asset(it, str(dest), asset_id)
        a.brand_id = brand_id
        a.folder = _folder_of(p, root_p)
        new_assets.append(a)

    grammar = store.load_grammar(brand_id)
    indexed = []
    for a in new_assets:
        a.quality = quality.verify_quality(a.png) if a.png else {"ok": False, "score": 0, "issues": ["no raster"]}
        indexed.append(quality.enrich(a, grammar))

    final = store.upsert_assets(brand_id, indexed)
    usable = [a for a in final if a.directly_usable and a.kind != "doc"]
    bad = [a for a in final if a.mismatches]
    log(f"catalog now {len(final)} assets ({len(usable)} usable, {len(bad)} with mismatches)")
    return {
        "brand_id": brand_id,
        "assets": len(final),
        "usable": len(usable),
        "mismatches": len(bad),
        "folders": sorted({a.folder for a in final}),
        "rules": [r.model_dump() for r in grammar.context_rules],
        "recipes": [r.model_dump() for r in grammar.recipes],
    }
