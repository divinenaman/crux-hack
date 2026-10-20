"""The layout-first canvas renderer.

One drawing core, three outputs:
  proof    — white canvas + REAL pieces (brand font text, exact element PNGs,
             designed shapes) — what the layout judge perfects BEFORE any pixels;
  keepout  — the same layout as solid black silhouettes on white — the keep-out
             guide the image model fills AROUND (white = fill, black = never touch);
  composite— a finished background + the real pieces on top (gallery/preview).

Text has no box behind it — font colour only — so it is drawn directly on the
field the bg fill will paint.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .. import store
from ..fidelity.typo import fit_asset_box, fit_text_block, load_font, resolve_font_path
from ..models import Brief, Placement

RATIO_SIZE = {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}


def canvas_size(ratio: str) -> tuple[int, int]:
    return RATIO_SIZE.get(ratio or "1:1", (1024, 1024))


def _brief_size(brief) -> tuple[int, int]:
    return canvas_size(getattr(brief, "ratio", None) or "1:1")


def _rect_px(rect: list[float], W: int, H: int) -> tuple[float, float, float, float]:
    x, y, w, h = [float(v) for v in rect]
    return x * W, y * H, w * W, h * H


def _font_path(brief: Brief, style: dict) -> str | None:
    src = str(style.get("font_src") or "")
    if src.startswith("/files/fonts/"):
        from .. import config

        p = config.WORKSPACE / "fonts" / src.split("/")[-1]
        if p.exists():
            return str(p)
    return resolve_font_path(str(style.get("font") or style.get("font_family") or ""))


def _draw_shape(d: ImageDraw.ImageDraw, p: Placement, W: int, H: int, fill, stroke=None, width=0):
    x, y, w, h = _rect_px(p.rect, W, H)
    st = p.style or {}
    shape = str(st.get("shape") or "rect").lower()
    if shape == "circle":
        d.ellipse([x, y, x + w, y + h], fill=fill, outline=stroke, width=width)
        return
    if shape == "pill":
        r = h / 2
        d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=stroke, width=width)
        return
    r = float(st.get("radius") or 0)
    if r > 0:
        d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=stroke, width=width)
    else:
        d.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=width)


def asset_paste_box(p: Placement, png: str, W: int, H: int) -> list[float]:
    """px box the asset image should occupy so its INK is aspect-fit centred in
    the placement rect (shared by the renderer and the manifest layer bbox)."""
    x, y, w, h = _rect_px(p.rect, W, H)
    try:
        asset = Image.open(png)
        sw, sh = asset.size
    except Exception:
        return [x, y, w, h]
    ax0, ay0, ax1, ay1 = fit_asset_box([0.0, 0.0, 1.0, 1.0], png)
    ink_w = max(1e-6, (ax1 - ax0) * sw)
    ink_h = max(1e-6, (ay1 - ay0) * sh)
    scale = min(w / ink_w, h / ink_h) if ink_w > 0 and ink_h > 0 else 1.0
    nw, nh = sw * scale, sh * scale
    ox = x + w / 2 - (ax0 + ax1) / 2 * nw
    oy = y + h / 2 - (ay0 + ay1) / 2 * nh
    return [ox, oy, nw, nh]


def _paste_asset(im: Image.Image, p: Placement, png: str, W: int, H: int, silhouette: bool = False):
    x, y, w, h = _rect_px(p.rect, W, H)
    if w < 2 or h < 2:
        return
    try:
        asset = Image.open(png).convert("RGBA")
    except Exception:
        return
    ox, oy, nw, nh = asset_paste_box(p, png, W, H)
    if nw < 1 or nh < 1:
        return
    asset = asset.resize((max(1, int(nw)), max(1, int(nh))), Image.LANCZOS)
    if silhouette:
        alpha = asset.split()[3]
        solid = Image.merge("RGBA", (Image.new("L", asset.size, 0),) * 3 + (alpha,))
        im.alpha_composite(solid, (int(ox), int(oy)))
    else:
        im.alpha_composite(asset, (int(ox), int(oy)))


def _draw_text(im: Image.Image, p: Placement, brief: Brief, W: int, H: int, silhouette: bool = False, wireframe: bool = False):
    x, y, w, h = _rect_px(p.rect, W, H)
    st = p.style or {}
    if w < 4 or h < 4:
        return
    fp = _font_path(brief, st)
    weight = int(st.get("weight") or 400)
    fit = fit_text_block(fp, p.content, w, h, multiline=True, weight=weight, line_gap=float(st.get("lineHeight") or 1.15))
    size = int(st.get("size") or 0) or fit["size"]
    if st.get("size"):
        fit = fit_text_block(fp, p.content, w, h, multiline=True, weight=weight, force_size=size)
        size = fit["size"]
    font = load_font(fp, size, weight)
    lines = fit["lines"]
    line_h = size * fit["line_gap"]
    block_h = (len(lines) - 1) * line_h + size * 1.05
    align = str(st.get("align") or "left")
    ty = y + max(0.0, (h - block_h) / 2)
    color = (0, 0, 0) if (silhouette or wireframe) else _rgb(st.get("color") or "#111111")
    d = ImageDraw.Draw(im)
    for ln in lines:
        lw = font.getlength(ln)
        if align == "center":
            tx = x + (w - lw) / 2
        elif align == "right":
            tx = x + w - lw
        else:
            tx = x
        if silhouette:
            # solid footprint bar (block-level keep-out, not glyph ink — the fill
            # must not sneak between letters)
            th = size * 1.05
            d.rectangle([x, ty, x + w, ty + th], fill=(0, 0, 0))
        else:
            d.text((tx, ty), ln, font=font, fill=color)
        ty += line_h


def _rgb(hexv: str) -> tuple[int, int, int]:
    h = (hexv or "#111111").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (17, 17, 17)


def _field_fill(f) -> tuple[int, int, int]:
    """Flat stand-in colour for a bg field on the proof (the colour contract)."""
    from ..brief.placements import field_dark, _intent_hex

    hx = _intent_hex(f.intent, f.color)
    if hx:
        return _rgb(hx)
    return (51, 65, 85) if field_dark(f) else (226, 232, 240)


def render_layout(brief: Brief, out_path: Path | str, brand_id: str = "", mode: str = "proof") -> str:
    """mode='proof'   — the wireframe: text + assets + shapes placed on a PLAIN
       canvas (the reference image the image model paints from);
       mode='keepout' — black silhouettes on white (edit-mask source)."""
    W, H = _brief_size(brief)
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    catalog = {a.id: a for a in store.load_catalog(brand_id)} if brand_id else {}
    silhouette = mode == "keepout"
    d = ImageDraw.Draw(im)

    # z-order: shapes → images → text (text always on top)
    ordered = sorted(brief.placements, key=lambda p: {"shape": 0, "image": 1, "text": 2}.get(p.kind, 1))
    for p in ordered:
        if p.kind == "shape":
            _draw_shape(
                d,
                p,
                W,
                H,
                fill=(0, 0, 0) if silhouette else _rgb(str((p.style or {}).get("fill") or "#CCCCCC")),
                stroke=None if silhouette else (_rgb((p.style or {}).get("stroke")) if (p.style or {}).get("stroke") else None),
                width=int((p.style or {}).get("strokeWidth") or 0),
            )
        elif p.kind == "image":
            a = catalog.get(p.asset_id)
            if a and a.png:
                _paste_asset(im, p, a.png, W, H, silhouette=silhouette)
        elif p.kind == "text":
            _draw_text(im, p, brief, W, H, silhouette=silhouette, wireframe=mode == "proof")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out)
    return str(out)


def render_composite(bg_path: str, brief: Brief, out_path: Path | str, brand_id: str = "") -> str:
    """Finished background + the real pieces on top — the gallery/preview image."""
    W, H = _brief_size(brief)
    try:
        bg = Image.open(bg_path).convert("RGBA")
        if bg.size != (W, H):
            bg = bg.resize((W, H), Image.LANCZOS)
    except Exception:
        bg = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    catalog = {a.id: a for a in store.load_catalog(brand_id)} if brand_id else {}
    ordered = sorted(brief.placements, key=lambda p: {"shape": 0, "image": 1, "text": 2}.get(p.kind, 1))
    for p in ordered:
        if p.kind == "shape":
            _draw_shape(
                ImageDraw.Draw(bg),
                p,
                W,
                H,
                fill=_rgb(str((p.style or {}).get("fill") or "#CCCCCC")),
                stroke=_rgb((p.style or {}).get("stroke")) if (p.style or {}).get("stroke") else None,
                width=int((p.style or {}).get("strokeWidth") or 0),
            )
        elif p.kind == "image":
            a = catalog.get(p.asset_id)
            if a and a.png:
                _paste_asset(bg, p, a.png, W, H)
        elif p.kind == "text":
            _draw_text(bg, p, brief, W, H)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out)
    return str(out)
