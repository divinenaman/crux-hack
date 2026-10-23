"""The layout-first canvas renderer.

One drawing core, three outputs:
  proof    — white canvas + REAL pieces (brand font text, exact element PNGs,
             designed shapes) — what the layout judge perfects BEFORE any pixels;
  keepout  — the same layout as solid black silhouettes on white — the keep-out
             guide the image model fills AROUND (white = fill, black = never touch);
  composite— a finished background + the real pieces on top (gallery/preview).

Text has no box behind it — font colour only — so it is drawn directly on the
field the bg fill will paint. Image/shape pieces carry optional style
"rotation" in degrees CLOCKWISE (tilt is part of the composition vocabulary;
never on text) — rotated around the piece centre.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .. import store
from ..fidelity.typo import as_int, as_weight, fit_asset_box, fit_text_block, load_font, resolve_font_path
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


def _dashed_rect(d: ImageDraw.ImageDraw, x0: float, y0: float, x1: float, y1: float, color, dash: float = 14.0, gap: float = 10.0, width: int = 3):
    import math

    plth = int(max(1, width))
    for (a, hor) in (((x0, y0, x1, y0), True), ((x1, y0, x1, y1), False), ((x1, y1, x0, y1), True), ((x0, y1, x0, y0), False)):
        (ax, ay, bx, by) = a
        from math import hypot
        length = hypot(bx - ax, by - ay)
        n = max(1, int(length // (dash + gap)))
        step = length / n
        u0, u1, v = (ax, bx, ay) if hor else (ay, by, ax)
        du = (step if u1 >= u0 else -step)
        for i in range(n):
            t0 = u0 + i * du
            t1 = t0 + (dash if u1 >= u0 else -dash)
            if hor:
                d.rectangle([min(t0, t1), v - plth / 2, max(t0, t1), v + plth / 2], fill=color)
            else:
                d.rectangle([v - plth / 2, min(t0, t1), v + plth / 2, max(t0, t1)], fill=color)


def _draw_rect(im: Image.Image, x: float, y: float, w: float, h: float, fill, stroke=None, radius=0, W: int = 0, H: int = 0):
    d = ImageDraw.Draw(im)
    if not fill and not stroke:
        return
    try:
        r = float(radius or 0)
    except Exception:
        r = 0.0
    if r >= min(w, h) / 2 or r >= 999:
        d.rounded_rectangle([x, y, x + w, y + h], radius=min(w, h) / 2, fill=fill, outline=stroke, width=2 if stroke else 0)
    elif r > 0:
        d.rounded_rectangle([x, y, x + w, y + h], radius=min(max(0, r), min(w, h) / 2), fill=fill)
    else:
        d.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=2 if stroke else 0)


def _draw_shape(im: Image.Image, p: Placement, W: int, H: int, fill, stroke=None, width=0):
    x, y, w, h = _rect_px(p.rect, W, H)
    st = p.style or {}
    shape = str(st.get("shape") or "rect").lower()
    rot = float(st.get("rotation") or 0)

    def _paint(d: ImageDraw.ImageDraw, x0: float, y0: float):
        if shape == "circle":
            d.ellipse([x0, y0, x0 + w, y0 + h], fill=fill, outline=stroke, width=width)
            return
        if shape == "pill":
            d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h / 2, fill=fill, outline=stroke, width=width)
            return
        r = float(st.get("radius") or 0)
        if r > 0:
            d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=r, fill=fill, outline=stroke, width=width)
        else:
            d.rectangle([x0, y0, x0 + w, y0 + h], fill=fill, outline=stroke, width=width)

    if abs(rot) > 0.5:
        # draw on a scratch layer, tilt clockwise around the piece centre
        layer = Image.new("RGBA", (max(1, int(w) + 2), max(1, int(h) + 2)), (0, 0, 0, 0))
        _paint(ImageDraw.Draw(layer), 1, 1)
        layer = layer.rotate(-rot, expand=True, resample=Image.BICUBIC)
        im.alpha_composite(layer, (int(x + w / 2 - layer.width / 2), int(y + h / 2 - layer.height / 2)))
    else:
        _paint(ImageDraw.Draw(im), x, y)


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


def paste_ghost(im: Image.Image, p: Placement, png: str, W: int, H: int, alpha: float = 0.30):
    """Asset rendered as a low-alpha ghost — palette reference for the model only."""
    asset = Image.new("RGBA", im.size, (0, 0, 0, 0))
    _paste_asset(asset, p, png, W, H)
    if asset.getbbox() is None:
        return
    a = asset.split()[3].point(lambda v: int(v * alpha))
    alpha_asset = asset.copy()
    alpha_asset.putalpha(a)
    im.alpha_composite(alpha_asset)


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
    rot = float((p.style or {}).get("rotation") or 0)
    if abs(rot) > 0.5:
        cx, cy = ox + nw / 2, oy + nh / 2
        asset = asset.rotate(-rot, expand=True, resample=Image.BICUBIC)  # clockwise degrees
        ox, oy = cx - asset.width / 2, cy - asset.height / 2
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
    weight = as_weight(st.get("weight"))
    fit = fit_text_block(fp, p.content, w, h, multiline=True, weight=weight, line_gap=float(st.get("lineHeight") or 1.15))
    size = as_int(st.get("size"), 0) or fit["size"]
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


def _paint_color(v, default=None):
    """Shape paint: 'none'/null/transparent = NO paint (never a black blob).
    Empty/missing falls back to default (the old grey fill behaviour)."""
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("none", "null", "transparent"):
        return None
    if not s:
        return default
    return _rgb(s)


def _field_fill(f) -> tuple[int, int, int]:
    """Flat stand-in colour for a bg field on the proof (the colour contract)."""
    from ..brief.placements import field_dark, _intent_hex

    hx = _intent_hex(f.intent, f.color)
    if hx:
        return _rgb(hx)
    return (51, 65, 85) if field_dark(f) else (226, 232, 240)


def render_proof_from_manifest(manifest, out_path: Path | str) -> str:
    """Edit-repaint wireframe — same anatomy as render_layout(mode='proof'): white
    base, dotted outlines for text zones and small shapes (no glyphs), real assets
    pasted with a dotted slot border, band-scale shapes keep their declared fill.
    NO glyphs, NO translucent pads — nothing for the model to copy but palette."""
    from ..models import Manifest

    m = Manifest.model_validate(manifest)
    W = int(float(m.canvas.get("w") or 1024))
    H = int(float(m.canvas.get("h") or 1024))
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    dashed = (204, 206, 218)
    screen = [
        l for l in m.layers
        if l.visible is not False and l.role not in ("background", "design")
    ]

    def _dashes(l, pad=4):
        x, y, w, h = [float(v) for v in l.bbox]
        if w < 4 and h < 4:
            return
        _dashed_rect(ImageDraw.Draw(im), max(0, x - pad), max(0, y - pad),
                     min(W, x + w + pad), min(H, y + h + pad), dashed)

    for l in screen:
        if l.type != "shape":
            continue
        st = l.style or {}
        x, y, w, h = [float(v) for v in l.bbox]
        fill = st.get("fill")
        if isinstance(fill, str) and fill.strip().lower() in ("none", "null", "transparent"):
            fill = None
        ar = (w * h) / float(W * H or 1)
        if fill and ar >= 0.10:
            shape = str(st.get("shape") or "rect").lower()
            radius = h / 2.0 if shape == "pill" else float(st.get("radius") or 0)
            _draw_rect(im, x, y, w, h, fill=_rgb(fill), stroke=None, radius=radius, W=W, H=H)
        else:
            _dashes(l, pad=8 if st.get("shape") == "pill" else 4)

    for l in screen:
        if l.type != "image" or not l.src:
            continue
        try:
            art = Image.open(Path(l.src)).convert("RGBA")
        except Exception:
            art = None
        x, y, w, h = [float(v) for v in l.bbox]
        st = l.style or {}
        nw, nh = max(1, int(w)), max(1, int(h))
        if art:
            art = art.resize((nw, nh), Image.LANCZOS)
            rot = float(st.get("rotation") or 0)
            if abs(rot) > 0.5:
                cx, cy = x + w / 2, y + h / 2
                art = art.rotate(-rot, expand=True, resample=Image.BICUBIC)
                x, y = cx - art.width / 2, cy - art.height / 2
            im.alpha_composite(art, (max(0, int(x)), max(0, int(y))))
        _dashes(l)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out)
    return str(out)


def render_layout(brief: Brief, out_path: Path | str, brand_id: str = "", mode: str = "proof") -> str:
    """mode='proof'   — the wireframe: text + assets + shapes placed on a PLAIN
       canvas (the reference image the image model paints from);
       mode='keepout' — black silhouettes on white (edit-mask source)."""
    W, H = _brief_size(brief)
    catalog = {a.id: a for a in store.load_catalog(brand_id)} if brand_id else {}
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))

    silhouette = mode == "keepout"

    # z-order: shapes → images → text (text always on top)
    dashed = (204, 206, 218)
    dashed_brand = (255, 255, 255)
    ordered = sorted(brief.placements, key=lambda p: {"shape": 0, "image": 1, "text": 2}.get(p.kind, 1))
    dashed_keys: set[tuple[str, str]] = set()
    for p in ordered:
        rect = _rect_px(p.rect, W, H)
        ar = float((p.rect or [0, 0, 0, 0])[2]) * float((p.rect or [0, 0, 0, 0])[3])
        key = (p.kind, str(p.rect))
        if mode == "proof" and p.kind not in ("image", "shape"):
            # text zones get NOTHING physical in the wire — copy contrast is the
            # live text layer's job; the model only sees the calm-zone words
            continue
        if mode == "proof" and p.kind == "shape" and ar < 0.10:
            if key in dashed_keys:
                continue
            dashed_keys.add(key)
            x, y, w, h = rect
            if p.kind == "shape":
                x -= 8; y -= 8; w += 16; h += 16
            if w >= 4 and h >= 4:
                _dashed_rect(ImageDraw.Draw(im), x, y, x + w, y + h, dashed)
            continue
        if p.kind == "shape":
            if mode == "proof":
                x, y, w, h = rect
                col = _paint_color((p.style or {}).get("fill"), None)
                if col is None:
                    # no declared colour — borrow the overlapped bg field's (keeps the
                    # model in the brand's palette instead of a grey void)
                    best_a = 0.0
                    for f in getattr(brief, "bg_fields", None) or []:
                        fx, fy, fw, fh = _rect_px(f.rect, W, H)
                        ax = max(0.0, min(x + w, fx + fw) - max(x, fx))
                        ay = max(0.0, min(y + h, fy + fh) - max(y, fy))
                        if ax * ay > best_a:
                            best_a, col = ax * ay, _rgb(f.color or "")
                _draw_rect(im, x, y, w, h, fill=col, stroke=_paint_color((p.style or {}).get("stroke")), radius=(p.style or {}).get("radius", 0), W=W, H=H)
            else:
                _draw_shape(
                    im,
                    p,
                    W,
                    H,
                    fill=(0, 0, 0) if silhouette else _paint_color((p.style or {}).get("fill"), (204, 204, 204)),
                    stroke=None if silhouette else _paint_color((p.style or {}).get("stroke")),
                    width=as_int((p.style or {}).get("strokeWidth"), 0),
                )
        elif p.kind == "image":
            a = catalog.get(p.asset_id)
            if a and a.png:
                # the REAL asset at full opacity — the model needs to see the true
                # logo/motif to colour-coordinate; dashed border marks its slot
                _paste_asset(im, p, a.png, W, H, silhouette=silhouette)
                if mode == "proof":
                    x, y, w, h = rect
                    if w >= 4 and h >= 4:
                        _dashed_rect(ImageDraw.Draw(im), x, y, x + w, y + h, dashed)
        elif p.kind == "text":
            _draw_text(im, p, brief, W, H, silhouette=silhouette, wireframe=mode == "proof")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out)
    return str(out)


def _composite_text_pad(bg: Image.Image, p: Placement, brief: Brief, W: int, H: int):
    """Soft, code-drawn pad beneath copy so it always reads on free-form art.

    The image model paints the world with zero boxes; the pad is composited here
    in the brief's backing colour — slightly translucent, feathered edges, so it
    never reads as a pasted rectangle."""
    role = str(getattr(p, "role", "") or "")
    if role == "cta":  # the pill shape beneath already gives its backing
        return
    x, y, w, h = _rect_px(p.rect, W, H)
    if w < 8 or h < 8:
        return
    col = (245, 243, 236)
    best_a = 0.0
    cx, cy = (x + w / 2) / W, (y + h / 2) / H
    for f in getattr(brief, "bg_fields", None) or []:
        fx, fy, fw, fh = _rect_px(f.rect, W, H)
        ax = max(0.0, min(x + w, fx + fw) - max(x, fx))
        ay = max(0.0, min(y + h, fy + fh) - max(y, fy))
        if ax * ay > best_a:
            best_a, col = ax * ay, _rgb(f.color or "")
    pad = w * 0.10, h * 0.35
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle([x - pad[0], y - pad[1], x + w + pad[0], y + h + pad[1]], radius=min(w, h) * 0.35 + 8, fill=tuple(col) + (222,))
    overlay = overlay.filter(ImageFilter.GaussianBlur(10))
    try:
        bg.alpha_composite(overlay)
    except Exception:
        pass


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
            ar = float((p.rect or [0, 0, 0, 0])[2]) * float((p.rect or [0, 0, 0, 0])[3])
            if ar >= 0.18:
                # band-scale zones were painted by the model — no opaque repaint, or
                # the fill's world is buried under a solid block
                continue
            _draw_shape(
                bg,
                p,
                W,
                H,
                fill=_paint_color((p.style or {}).get("fill"), (204, 204, 204)),
                stroke=_paint_color((p.style or {}).get("stroke")),
                width=as_int((p.style or {}).get("strokeWidth"), 0),
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
