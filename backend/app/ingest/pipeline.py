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


def _trim_solid(im: "Image.Image") -> "Image.Image":
    """Vision bboxes are loose — trim near-solid margins so the element fills
    the crop. Only fires when the border ring is actually uniform (flat bg)."""
    from PIL import Image, ImageChops

    rgb = im.convert("RGB")
    w, h = rgb.size
    if w < 24 or h < 24:
        return im
    ring = Image.new("L", (w, h), 0)
    from PIL import ImageDraw

    d = ImageDraw.Draw(ring)
    d.rectangle([0, 0, w - 1, h - 1], outline=255, width=max(2, min(w, h) // 40))
    px = [rgb.getpixel((x, y)) for x in range(0, w, max(1, w // 24)) for y in (1, h - 2)]
    px += [rgb.getpixel((x, y)) for y in range(0, h, max(1, h // 24)) for x in (1, w - 2)]
    if not px:
        return im
    var = max(
        max(p[i] for p in px) - min(p[i] for p in px)
        for i in range(3)
    )
    if var > 36:  # busy border — can't tell bg, leave as-is
        return im
    bg = tuple(sorted(p[i] for p in px)[len(px) // 2] for i in range(3))
    bg_im = Image.new("RGB", (w, h), bg)
    diff = ImageChops.difference(rgb, bg_im).convert("L").point(lambda v: 255 if v > 26 else 0)
    bbox = diff.getbbox()
    if not bbox:
        return im
    pad = 3
    bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad))
    if (bbox[2] - bbox[0]) < 16 or (bbox[3] - bbox[1]) < 16:
        return im
    return im.crop(bbox)


def _crop_element(src: Path, bbox: list[float], dest: Path, pad: float = 0.005, trim: bool = True) -> Path | None:
    """Harvest a sub-element (logo/charm/ui…) out of a full image."""
    try:
        from PIL import Image

        im = Image.open(src)
        W, H = im.size
        x, y, w, h = [float(v) for v in bbox]
        x0, y0 = max(0.0, x - pad) * W, max(0.0, y - pad) * H
        x1, y1 = min(1.0, x + w + pad) * W, min(1.0, y + h + pad) * H
        if x1 - x0 < 16 or y1 - y0 < 16:
            return None
        crop = im.crop((int(x0), int(y0), int(x1), int(y1)))
        if trim:
            crop = _trim_solid(crop)
        if crop.size[0] < 16 or crop.size[1] < 16:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dest)
        return dest
    except Exception:
        return None


def _apply_tighten(png: Path, bbox: list[float], trim: bool) -> None:
    """Recrop an already-saved loose crop to a tight vision bbox (fractions of it)."""
    try:
        from PIL import Image

        im = Image.open(png)
        W, H = im.size
        x, y, w, h = [float(v) for v in bbox]
        x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
        w, h = max(0.02, min(1.0 - x, w)), max(0.02, min(1.0 - y, h))
        pad = 0.004
        box = (
            int(max(0.0, x - pad) * W),
            int(max(0.0, y - pad) * H),
            int(min(1.0, x + w + pad) * W),
            int(min(1.0, y + h + pad) * H),
        )
        crop = im.crop(box)
        if trim:
            crop = _trim_solid(crop)
        if crop.size[0] < 12 or crop.size[1] < 12:
            return
        crop.save(png)
    except Exception:
        return


_EXTRACT_KIND = {"logo": "logo", "charm": "charm", "ui": "ui-shot", "bloom": "bloom", "photo": "photo-scene"}


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
        try:
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
        except Exception as e:
            log(f"grammar extraction skipped ({e}) — assets still indexed")

    assets_dir = config.brand_assets_dir(brand_id)

    for sheet in chapter_sheets:
        try:
            cells = grid.crop_cells(sheet, assets_dir / f"{_sid(sheet.parent.name, sheet.stem)}_cells", _sid(sheet.parent.name, sheet.stem))
            if len(cells) < 3:
                continue
            log(f"grid-cropping composite sheet {sheet.name} -> {len(cells)} individual assets")
            names = classify.name_cells(str(sheet), [c["png"] for c in cells])
        except Exception as e:
            log(f"grid sheet {sheet.name} skipped ({e})")
            continue
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
        try:
            items += classify.classify_batch(chunk, str(root_p))
        except Exception as e:
            log(f"classify unavailable ({str(e)[:80]}) — using filename metadata")
            break

    by_file = {it.get("file", ""): it for it in items}
    pending_tighten: list[tuple[str, Path, str, bool]] = []
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

        # harvest reusable sub-elements (logo/charm/ui card/shape) out of full images.
        # stage 1: loose crop (generous pad, no trim) so nothing gets clipped.
        for j, ex in enumerate((it.get("extractions") or [])[:5]):
            if not isinstance(ex, dict):
                continue
            role = str(ex.get("role") or "accent")
            ex_name = classify._as_str(ex.get("name")) or f"{a.name} — {role}"
            crop = _crop_element(dest, ex.get("bbox") or [], assets_dir / f"{asset_id}__e{j + 1}.png", pad=0.15, trim=False)
            if not crop:
                continue
            log(f"extracted '{ex_name}' ({role}) from {p.name}")
            pending_tighten.append((f"{asset_id}__e{j + 1}", crop, ex_name, role in ("logo", "charm", "ui")))
            new_assets.append(
                Asset(
                    id=f"{asset_id}__e{j + 1}",
                    name=ex_name,
                    kind=_EXTRACT_KIND.get(role, "illustration"),
                    tags=classify._as_list(ex.get("tags")) or [role],
                    semantic=classify._as_str(ex.get("semantic")),
                    usage=f"Extracted {role} element from '{a.name}' — use as a real brand asset.",
                    role_hints=[role, "accent"],
                    png=str(crop),
                    source=str(p),
                    directly_usable=True,
                    exact_required=role in ("logo", "charm", "ui"),
                    brand_id=brand_id,
                    folder=a.folder,
                )
            )

    # stage 2: vision tighten pass — recrop each loose crop to just its named element
    if pending_tighten:
        try:
            tight = classify.tighten_crops([(cid, str(png), name) for cid, png, name, _ in pending_tighten])
        except Exception as e:
            log(f"tighten skipped ({str(e)[:60]}) — keeping loose crops")
            tight = {}
        n = 0
        for cid, png, name, exact in pending_tighten:
            bb = tight.get(cid)
            if bb:
                _apply_tighten(Path(png), bb, trim=not exact)  # never solid-trim exact assets (logo badge bg is content)
                n += 1
            else:
                # tighten failed — at least drop flat margins (no-op on busy photo bgs)
                _apply_tighten(Path(png), [0.0, 0.0, 1.0, 1.0], trim=True)
        log(f"tightened {n}/{len(pending_tighten)} extracted crops")

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
