from pathlib import Path

from .. import config, store
from ..models import Brief, Layer, Manifest
from .match import find_assets, paste_exact
from .textfit import fit_asset_box

TEXT_ROLES = {"headline", "text_headline", "sub", "text_sub", "subhead", "body", "text_body", "cta"}
LOGO_ROLES = {"logo", "footer", "logo_footer"}

# logo colourway hint (zone content) -> asset-name token
_LOGO_HINTS = (("white", "white"), ("navy", "dark"), ("dark", "dark"), ("sky", "light"), ("light", "light"), ("blue", "blue"))


def _paste_bbox(bbox: list[float], W: float, H: float, asset_png: str) -> list[float]:
    """px [x,y,w,h] -> padding-compensated px box so the asset's ink lands on bbox."""
    frac = fit_asset_box([bbox[0] / W, bbox[1] / H, (bbox[0] + bbox[2]) / W, (bbox[1] + bbox[3]) / H], asset_png)
    x0, y0, x1, y1 = frac
    return [x0 * W, y0 * H, (x1 - x0) * W, (y1 - y0) * H]


def build_manifest(brand_id: str, job_id: str, variant_id: str, design_path: str, brief: Brief) -> Manifest:
    W, H = _size(design_path, brief.ratio)
    layers: list[Layer] = [
        Layer(type="raster", role="design", src=design_path, locked=True, bbox=[0, 0, float(W), float(H)])
    ]

    hits = find_assets(brand_id, design_path, [f.asset_id for f in brief.slots])
    out_dir = config.brand_out_dir(brand_id) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    logo_hint = next((z.content for z in brief.zones if z.role in LOGO_ROLES or "logo" in z.role), "")

    def resolve_asset(fill) -> "object | None":
        """Logo roles must resolve to a real logo asset — never a decorative fill."""
        a = store.get_asset(brand_id, fill.asset_id)
        if (fill.role in LOGO_ROLES or "logo" in fill.role) and (not a or a.kind != "logo"):
            a = _pick_logo_asset(brand_id, logo_hint) or a
        return a

    def zone_bbox(role: str) -> list[float] | None:
        for z in brief.zones:
            if z.role == role or z.role.replace("text_", "") == role.replace("text_", ""):
                x, y, w, h = z.rect
                return [x * W, y * H, w * W, h * H]
        return None

    for fill in brief.slots:
        if (fill.role in LOGO_ROLES or "logo" in fill.role) and any(
            z.style.get("replace") is False for z in brief.zones if z.role in LOGO_ROLES or "logo" in z.role
        ):
            continue  # logo kept baked — no replacement layer
        asset = resolve_asset(fill)
        if not asset:
            continue
        is_logo_fill = fill.role in LOGO_ROLES or "logo" in fill.role
        hit = hits.get(fill.asset_id) or {}
        score = float(hit.get("score") or 0)
        hb = hit.get("bbox")
        plausible = False
        if hb:
            bw, bh = float(hb[2]), float(hb[3])
            plausible = min(bw, bh) >= 0.03 * min(W, H) and (bw * bh) >= 0.003 * W * H
        if is_logo_fill:
            # measured zone placement — exact by construction; NCC on wordmarks
            # is brittle and the slot fill may reference the wrong asset entirely
            zb = zone_bbox(fill.role) or zone_bbox("logo_footer") or zone_bbox("logo")
            if zb is None:
                continue
            bbox, placed_by = zb, "zone"
        elif score > 0.5 and hb and plausible:
            bbox = [float(v) for v in hb]
            placed_by = "match"
        else:
            zb = zone_bbox(fill.role) or (zone_bbox("logo_footer") if fill.role == "logo" else None)
            if zb is None:
                continue
            bbox = zb
            placed_by = "zone"
        src = asset.png
        if asset.exact_required:
            exact = out_dir / f"{variant_id}_{asset.id}.png"
            bbox = _paste_bbox(bbox, W, H, asset.png)
            paste_exact(brand_id, design_path, asset.id, bbox, str(exact))
            src = str(exact)
        layers.append(
            Layer(
                type="image",
                role=fill.role,
                src=src,
                asset_id=fill.asset_id,
                bbox=bbox,
                style={"placed_by": placed_by, "match_score": score, "why": fill.why, "placement": fill.placement},
                locked=False,
            )
        )

    for z in brief.zones:
        if z.style.get("replace") is False:
            continue  # element stays baked into the design raster — no live layer
        is_logo = z.role in LOGO_ROLES or "logo" in z.role
        if is_logo:
            if any(l.type == "image" and l.role in ("logo", "footer", "logo_footer") for l in layers):
                continue
            fill = next((f for f in brief.slots if f.role == "logo"), None)
            asset = resolve_asset(fill) if fill else _pick_logo_asset(brand_id, z.content or "")
            if not asset:
                continue
            x, y, w, h = z.rect
            bbox = [x * W, y * H, w * W, h * H]
            src = asset.png
            if asset.exact_required:
                exact = out_dir / f"{variant_id}_{asset.id}.png"
                bbox = _paste_bbox(bbox, W, H, asset.png)
                paste_exact(brand_id, design_path, asset.id, bbox, str(exact))
                src = str(exact)
            layers.append(Layer(type="image", role="logo", src=src, asset_id=asset.id, bbox=bbox, style={"placed_by": "zone"}, locked=False))
            continue

        content = _content(brief, z)
        if not content:
            continue
        x, y, w, h = z.rect
        bbox = [x * W, y * H, w * W, h * H]
        style = {
            "font": z.style.get("font_family") or config.BRAND_FONT,
            "font_src": z.style.get("font_src", ""),
            "fallback": config.BRAND_FONT_FALLBACK,
            "color": z.style.get("color", "#FFFFFF" if z.role == "cta" else "#000856"),
            "align": z.style.get("align", "center" if z.role == "cta" else "left"),
            "weight": z.style.get("weight", 700 if z.role in TEXT_ROLES and z.role != "body" and z.role != "text_body" else 400),
            "size": z.style.get("size", _auto_size(z.role, h * H)),
            "padding": z.style.get("padding", 0),
            "lineHeight": z.style.get("lineHeight", 1.2),
            "draw_bg": z.style.get("draw_bg", True),
            "measured": z.style.get("measured", False),
            "text_free": True,
        }
        layers.append(Layer(type="text", role=z.role, content=content, bbox=bbox, style=style, locked=False))

    return Manifest(
        job_id=job_id,
        variant_id=variant_id,
        canvas={"w": float(W), "h": float(H)},
        ratio=brief.ratio,
        layers=layers,
        design_src=design_path,
    )


def _content(brief: Brief, z) -> str:
    if z.role in ("headline", "text_headline"):
        return brief.copy.headline
    if z.role in ("sub", "text_sub", "subhead"):
        return brief.copy.sub
    if z.role in ("body", "text_body"):
        return "\n".join(brief.copy.body)
    if z.role == "cta":
        return brief.copy.cta
    return z.content or ""


def _pick_logo_asset(brand_id: str, hint: str):
    hint_l = hint.lower()
    logos = [a for a in store.load_catalog(brand_id) if a.kind == "logo" or "logo" in a.name.lower()]
    if not logos:
        return None
    for key, name_key in _LOGO_HINTS:
        if key in hint_l:
            for a in logos:
                if name_key in a.name.lower():
                    return a
    return logos[0]


def _size(path: str, ratio: str) -> tuple[int, int]:
    from PIL import Image

    try:
        return Image.open(path).size
    except Exception:
        return {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}.get(ratio, (1024, 1024))


def _auto_size(role: str, box_h: float) -> float:
    if role in ("headline", "text_headline"):
        return max(28.0, box_h * 0.55)
    if role in ("sub", "text_sub", "subhead"):
        return max(18.0, box_h * 0.4)
    if role == "cta":
        return max(16.0, box_h * 0.42)
    return max(12.0, box_h * 0.28)
