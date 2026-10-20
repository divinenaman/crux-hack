"""Font resolution + text fitting with real font metrics (no crop, ever).

Used by the layout renderer (proof + composite) and the Konva manifest layers.
Extracted from the old textfit module — the measure/strip machinery is archived.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


def resolve_font_path(preferred: str = "") -> str | None:
    from ..ingest.fonts import ensure_font_file

    for name in (preferred, "Figtree", "Inter"):
        hit = ensure_font_file(name) if name else None
        if hit:
            return hit
    return None


def have_corresponding_font(font_hint: str) -> bool:
    """True only when the identified brand font resolves to a real font file."""
    if not font_hint:
        return False
    from ..ingest.fonts import find_font_file

    return bool(find_font_file(font_hint))


def as_weight(v) -> int:
    """Tolerant font-weight coercion — planners write 700, '700', 'bold', …"""
    if isinstance(v, bool):
        return 400
    if isinstance(v, (int, float)):
        return max(100, min(900, int(v)))
    s = str(v or "").strip().lower()
    named = {
        "thin": 100, "light": 300, "normal": 400, "regular": 400, "book": 400,
        "medium": 500, "semibold": 600, "semi-bold": 600, "demi": 600,
        "bold": 700, "strong": 700, "heavy": 800, "black": 900,
    }
    if s in named:
        return named[s]
    try:
        return max(100, min(900, int(float(s))))
    except Exception:
        return 400


def as_int(v, default: int = 0) -> int:
    """Tolerant int coercion for style fields (size, padding, strokeWidth…)."""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def load_font(font_path: str | None, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    """Load a face at px size; apply the weight axis on variable fonts when bold."""
    size = max(6, int(size))
    f = None
    if font_path:
        try:
            f = ImageFont.truetype(font_path, size)
        except Exception:
            f = None
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:  # older Pillow
            f = ImageFont.load_default()
    if f and weight >= 700:
        for setter, arg in (("set_variation_by_name", "Bold"), ("set_variation_by_axes", [700])):
            try:
                getattr(f, setter)(arg)
                break
            except Exception:
                continue
    return f


def _wrap(font: ImageFont.FreeTypeFont, text: str, max_w: float) -> list[str]:
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = f"{line} {word}".strip()
            if line and font.getlength(cand) > max_w:
                out.append(line)
                line = word
            else:
                line = cand
        out.append(line)
    return out


def fit_text_block(
    font_path: str | None,
    text: str,
    w_px: float,
    h_px: float,
    multiline: bool = True,
    weight: int = 400,
    line_gap: float = 1.15,
    force_size: int | None = None,
) -> dict:
    """Fit copy into a w×h box with real font metrics — guaranteed no crop.

    Returns {"size", "lines" (pre-wrapped), "line_gap"}. With force_size the
    text is wrapped at that size (no search)."""
    flat = (text or "").replace("\n", " ").strip() or " "
    wrap_w = max(8.0, float(w_px))

    def pack(size: int) -> tuple[list[str], float, float]:
        f = load_font(font_path, size, weight)
        lines = _wrap(f, flat, wrap_w) if multiline else [flat]
        try:
            asc, desc = f.getmetrics()
        except Exception:
            asc, desc = int(size * 0.8), int(size * 0.25)
        wmax = max((f.getlength(ln) for ln in lines), default=0.0)
        th = (len(lines) - 1) * size * line_gap + (asc + desc)
        return lines, wmax, th

    if force_size:
        size = max(6, int(force_size))
        lines, _, _ = pack(size)
        return {"size": size, "lines": lines, "line_gap": line_gap}

    lo, hi, best = 6, max(6, int(h_px)), None
    while lo <= hi:  # largest size whose wrapped ink fits BOTH dims
        mid = (lo + hi) // 2
        lines, wmax, th = pack(mid)
        if wmax <= wrap_w and th <= h_px:
            best = {"size": mid, "lines": lines, "line_gap": line_gap}
            lo = mid + 1
        else:
            hi = mid - 1
    return best or {"size": 6, "lines": pack(6)[0], "line_gap": line_gap}


def fit_font_size(font_path: str, text: str, w_px: float, h_px: float, multiline: bool) -> int:
    """Pick the pt size whose rendered ink best matches the measured box."""
    cap = max(10, int(h_px * (0.7 if multiline else 1.2)))
    best, best_err = max(8, int(h_px * 0.8)), 1e18
    for size in range(8, cap):
        try:
            f = ImageFont.truetype(font_path, size)
        except Exception:
            return best
        probe = Image.new("L", (int(max(w_px * 1.4, 80)), int(max(h_px * 4, 120))), 0)
        d = ImageDraw.Draw(probe)
        if multiline:
            y = 0
            for ln in _wrap(f, text, w_px * 1.05):
                d.text((0, y), ln, font=f, fill=255)
                y += int(size * 1.18)
        else:
            d.text((0, 0), text, font=f, fill=255)
        bb = probe.getbbox()
        if not bb:
            continue
        rw, rh = bb[2] - bb[0], bb[3] - bb[1]
        err = abs(rw - w_px) + abs(rh - h_px) * (0.5 if multiline else 1.0)
        if err < best_err:
            best_err, best = err, size
    return best


def asset_ink_box(png_path: str) -> tuple[float, float, float, float]:
    """Ink bbox of an asset as fractions of the asset image (transparent padding)."""
    import numpy as np

    from ..imutil import ensure_raster

    try:
        im = Image.open(ensure_raster(png_path)).convert("RGBA")
    except Exception:
        return (0.0, 0.0, 1.0, 1.0)
    a = np.asarray(im)[:, :, 3] > 16
    ys, xs = np.where(a)
    if not len(ys):
        return (0.0, 0.0, 1.0, 1.0)
    W, H = im.size
    return (xs.min() / W, ys.min() / H, (xs.max() + 1) / W, (ys.max() + 1) / H)


def fit_asset_box(frac_bbox: list[float], asset_png: str) -> list[float]:
    """Expand a tight-ink target box so the asset's own ink lands exactly on it."""
    x0, y0, x1, y1 = frac_bbox
    ax0, ay0, ax1, ay1 = asset_ink_box(asset_png)
    if ax1 <= ax0 or ay1 <= ay0:
        return frac_bbox
    w, h = x1 - x0, y1 - y0
    full_w = w / max(1e-6, ax1 - ax0)
    full_h = h / max(1e-6, ay1 - ay0)
    return [x0 - ax0 * full_w, y0 - ay0 * full_h, x0 - ax0 * full_w + full_w, y0 - ay0 * full_h + full_h]
