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
    """Layers = the deterministic replace pass: text (brand font) and the direct
    logo asset, each in the SAME bbox it occupied in the bake (measured). No RAG,
    no added elements — everything else stays as generated."""
    W, H = _size(design_path, brief.ratio)
    layers: list[Layer] = [
        Layer(type="raster", role="design", src=design_path, locked=True, bbox=[0, 0, float(W), float(H)])
    ]
    out_dir = config.brand_out_dir(brand_id) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    logo_hint = next((z.content for z in brief.zones if z.role in LOGO_ROLES or "logo" in z.role), "")

    for z in brief.zones:
        if z.style.get("replace") is False:
            continue  # element stays baked into the design raster — no live layer
        is_logo = z.role in LOGO_ROLES or "logo" in z.role
        x, y, w, h = z.rect
        bbox = [x * W, y * H, w * W, h * H]

        if is_logo:
            # DIRECT replacement: the brand's own logo asset (name/colourway match),
            # pasted in the measured bbox. Not retrieval — never a random asset.
            asset = _pick_logo_asset(brand_id, z.content or logo_hint)
            if not asset or not asset.png:
                continue
            bbox = _paste_bbox(bbox, W, H, asset.png)  # asset ink lands on the measured box
            layers.append(
                Layer(
                    type="image",
                    role="logo",
                    src=asset.png,
                    asset_id=asset.id,
                    bbox=bbox,
                    style={"placed_by": "measured", "replace": True, "why": "direct logo asset in the baked logo bbox"},
                    locked=False,
                )
            )
            continue

        content = _content(brief, z)
        if not content or z.role not in TEXT_ROLES:
            continue  # non-text wireframe zones (bg/photo/charm…) are layout spec only
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
    # direct pick: the dominant logo (e.g. 3x "Xero logo" beats a one-off partner lockup)
    from collections import Counter

    freq = Counter(a.name.strip().lower() for a in logos)
    return max(logos, key=lambda a: (freq[a.name.strip().lower()], -len(a.name)))


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
