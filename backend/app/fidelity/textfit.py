"""Deterministic + smart overlay metrics and replacement policy.

Flow: DeepSeek Flash proposes coarse element windows (smart), pure CV tightens
each window to the exact ink bbox / stroke colour / font size (deterministic).
Only elements we CAN replace are replaced (font for text, matching asset for
logo) — everything else stays baked into the design raster, intact.
All boxes are normalized [x0, y0, x1, y1].
"""
import json
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import llm
from ..imutil import ensure_raster
from ..models import Brief

DETECT_SYSTEM = """You detect text and logo elements in ads. Reply ONLY JSON:
{"elements":[{"label": str, "text": str, "bbox_2d": [ymin, xmin, ymax, xmax]}]}
bbox_2d NORMALIZED 0..1 as [ymin, xmin, ymax, xmax] — tight around the visible element."""


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


def _norm_s(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _to_xyxy(bb: list[float]) -> list[float]:
    """DeepSeek [ymin,xmin,ymax,xmax] -> [x0,y0,x1,y1]."""
    y0, x0, y1, x1 = bb
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _rect_to_xyxy(rect: list[float]) -> list[float]:
    """Zone rect [x,y,w,h] -> [x0,y0,x1,y1]."""
    x, y, w, h = rect
    return [x, y, x + w, y + h]


def detect_windows(image_path: str, brief: Brief) -> dict[str, list[float]]:
    """Coarse per-role windows [x0,y0,x1,y1] from the vision model."""
    want: dict[str, str] = {}
    for z in brief.zones:
        c = (z.content or "").strip()
        if z.role in ("headline", "text_headline"):
            c = brief.copy.headline
        elif z.role in ("sub", "text_sub", "subhead"):
            c = brief.copy.sub
        elif z.role in ("body", "text_body"):
            c = " ".join(brief.copy.body)
        elif z.role == "cta":
            c = brief.copy.cta
        if c or "logo" in z.role or z.role == "footer":
            want[z.role] = c

    lines = "\n".join(f'- "{v}" (element role: {k})' for k, v in want.items() if v)
    try:
        raw = llm.chat_vision(
            DETECT_SYSTEM,
            [
                {
                    "type": "text",
                    "text": f"Find these elements and return one entry each (text must match exactly):\n{lines}\nAlso mark the brand logo/wordmark as label 'logo'.",
                },
                llm.img_part(image_path, detail="high"),
            ],
            model="flash",
            json_mode=True,
        )
        data = _parse(raw)
    except Exception:
        return {}

    out: dict[str, list[float]] = {}
    for e in data.get("elements", []):
        bb = e.get("bbox_2d")
        if not (isinstance(bb, list) and len(bb) == 4 and all(isinstance(v, (int, float)) for v in bb)):
            continue
        box = _to_xyxy([max(0.0, min(1.0, float(v))) for v in bb])
        et, el = _norm_s(str(e.get("text", ""))), _norm_s(str(e.get("label", "")))
        for role, content in want.items():
            if role in out:
                continue
            cn = _norm_s(content)
            if (cn and (cn in et or et in cn)) or (el and (role in el or el in role)) or (("logo" in role or role == "footer") and el == "logo"):
                out[role] = box
    return out


def _ink_stats(crop: Image.Image) -> tuple[tuple[int, int, int] | None, Image.Image]:
    """Binary ink mask (content pixels vs local background) + stroke colour."""
    rgb = np.asarray(crop.convert("RGB"), dtype=np.int16)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).reshape(-1, 3)
    bg = np.median(border, axis=0)
    dist = np.abs(rgb - bg).sum(axis=2)
    thresh = max(70.0, float(np.percentile(dist, 93)) * 0.45)
    mask = Image.fromarray(((dist > thresh) * 255).astype(np.uint8), "L")
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    a = np.asarray(mask) > 128
    if not a.any():
        return None, mask
    px = rgb[a]
    color = np.median(px, axis=0).astype(int)
    return tuple(int(v) for v in color), mask


def _mask_bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    a = np.asarray(mask) > 128
    ys, xs = np.where(a)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def resolve_font_path(preferred: str = "") -> str | None:
    from ..ingest.fonts import ensure_font_file

    for name in (preferred, "Figtree", "Inter"):
        hit = ensure_font_file(name) if name else None
        if hit:
            return hit
    return None


def have_corresponding_font(font_hint: str) -> bool:
    """True only when the identified brand font resolves to a real font file.

    A metric-similar fallback is NOT 'the corresponding font' — policy: if we
    don't have it, we don't replace the text (design stays intact)."""
    if not font_hint:
        return False
    from ..ingest.fonts import find_font_file

    return bool(find_font_file(font_hint))


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
        bb = _mask_bbox(probe)
        if not bb:
            continue
        rw, rh = bb[2] - bb[0], bb[3] - bb[1]
        err = abs(rw - w_px) + abs(rh - h_px) * (0.5 if multiline else 1.0)
        if err < best_err:
            best_err, best = err, size
    return best


def measure_ink(image_path: str, window: list[float], content: str = "", multiline: bool = False, font_hint: str = "") -> dict:
    """Tight deterministic metrics for one element inside a coarse window [x0,y0,x1,y1]."""
    im = Image.open(ensure_raster(image_path)).convert("RGB")
    W, H = im.size
    x0, y0, x1, y1 = window
    pad = 0.01
    box = (
        int(max(0.0, x0 - pad) * W),
        int(max(0.0, y0 - pad) * H),
        int(min(1.0, x1 + pad) * W),
        int(min(1.0, y1 + pad) * H),
    )
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return {}
    crop = im.crop(box)
    color, mask = _ink_stats(crop)
    bb = _mask_bbox(mask)
    if not bb:
        return {}
    ix0, iy0, ix1, iy1 = bb
    ink_w, ink_h = ix1 - ix0, iy1 - iy0
    out = {
        "bbox": [
            (box[0] + ix0) / W,
            (box[1] + iy0) / H,
            (box[0] + ix1) / W,
            (box[1] + iy1) / H,
        ],
        "color": "#%02x%02x%02x" % color if color else "",
        "ink_w": float(ink_w),
        "ink_h": float(ink_h),
    }
    fp = resolve_font_path(font_hint) if have_corresponding_font(font_hint) else None
    if fp and content:
        out["size"] = fit_font_size(fp, content, ink_w, ink_h, multiline)
        out["font_path"] = fp
    else:
        out["size"] = max(8, int(ink_h * (0.72 if multiline else 0.95)))
    return out


def cta_pill_metrics(image_path: str, window: list[float]) -> dict:
    """For CTA: measure the pill (button) box + the label ink inside it."""
    im = Image.open(ensure_raster(image_path)).convert("RGB")
    W, H = im.size
    x0, y0, x1, y1 = window
    box = (
        int(max(0.0, x0 - 0.01) * W),
        int(max(0.0, y0 - 0.01) * H),
        int(min(1.0, x1 + 0.01) * W),
        int(min(1.0, y1 + 0.01) * H),
    )
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return {}
    crop = im.crop(box)
    pill_color, pill_mask = _ink_stats(crop)
    bb = _mask_bbox(pill_mask)
    if not bb or not pill_color:
        return {}
    pill_bbox = [(box[0] + bb[0]) / W, (box[1] + bb[1]) / H, (box[0] + bb[2]) / W, (box[1] + bb[3]) / H]
    arr = np.asarray(crop.convert("RGB"), dtype=np.int16)
    inner = arr[bb[1] : bb[3], bb[0] : bb[2]]
    if not inner.size:
        return {"pill_bbox": pill_bbox}
    d = np.abs(inner - np.array(pill_color)).sum(axis=2)
    lab = d > 150
    ys, xs = np.where(lab)
    if not len(ys):
        return {"pill_bbox": pill_bbox}
    label_bbox = [
        (box[0] + bb[0] + int(xs.min())) / W,
        (box[1] + bb[1] + int(ys.min())) / H,
        (box[0] + bb[0] + int(xs.max()) + 1) / W,
        (box[1] + bb[1] + int(ys.max()) + 1) / H,
    ]
    label_color = "#%02x%02x%02x" % tuple(np.median(inner[lab], axis=0).astype(int))
    return {"pill_bbox": pill_bbox, "label_bbox": label_bbox, "label_color": label_color}


def replacement_plan(brief: Brief, brand_id: str, font_hint: str = "") -> dict[str, dict]:
    """Per-role decision: replace with our render/asset, or keep baked.

    Policy: text is replaced ONLY if we have the corresponding font; the logo
    is replaced ONLY if we have a matching brand asset. Everything else stays
    baked into the design raster (design remains intact)."""
    from .. import store

    have_font = have_corresponding_font(font_hint)
    plan: dict[str, dict] = {}
    logo_hint = ""
    logo_ok = False

    for z in brief.zones:
        is_logo = "logo" in z.role or z.role in ("footer", "logo_footer")
        if is_logo and not logo_hint:
            logo_hint = z.content or ""
            logos = [a for a in store.load_catalog(brand_id) if a.kind == "logo"]
            # 'same exact text' — the asset wordmark must match the baked brand mark
            hint_n = _norm_s(logo_hint)
            logo_ok = any(
                (any(t in _norm_s(a.name) for t in hint_n.split() if len(t) > 2) or "xero" in _norm_s(a.name))
                for a in logos
            ) if hint_n else bool(logos)
        plan[z.role] = {
            "replace": bool(logo_ok) if is_logo else have_font,
            "kind": "logo" if is_logo else "text",
            "reason": (
                ("logo asset matches baked wordmark") if is_logo and logo_ok else
                ("no matching logo asset") if is_logo else
                (f"font '{font_hint}' available" if have_font else f"font '{font_hint or 'unknown'}' not available")
            ),
        }
    return plan


def measure_overlays(image_path: str, brief: Brief, font_hint: str = "") -> dict[str, dict]:
    """Per-role metrics for every text zone + logo, on the PRE-strip bake."""
    windows = detect_windows(image_path, brief)
    out: dict[str, dict] = {}
    for z in brief.zones:
        is_logo = "logo" in z.role or z.role in ("footer", "logo_footer")
        content, multiline = "", False
        if not is_logo:
            if z.role in ("headline", "text_headline"):
                content = brief.copy.headline
            elif z.role in ("sub", "text_sub", "subhead"):
                content = brief.copy.sub
            elif z.role in ("body", "text_body"):
                content = "\n".join(brief.copy.body)
                multiline = True
            elif z.role == "cta":
                content = brief.copy.cta
            else:
                content = z.content or ""
            if not content:
                continue
        win = windows.get(z.role) or _rect_to_xyxy([float(v) for v in z.rect])
        if win[2] <= win[0] or win[3] <= win[1]:
            win = _rect_to_xyxy([float(v) for v in z.rect])

        if z.role == "cta":
            cm = cta_pill_metrics(image_path, win)
            lab = cm.get("label_bbox") or win
            m = measure_ink(image_path, list(lab), content=content, multiline=False, font_hint=font_hint)
            if not m:
                continue
            m["bbox"] = cm.get("pill_bbox") or m["bbox"]  # zone sits on the button
            m["label_bbox"] = cm.get("label_bbox") or m["bbox"]
            if cm.get("label_color"):
                m["color"] = cm["label_color"]
        else:
            m = measure_ink(image_path, win, content=content, multiline=multiline, font_hint=font_hint)
            if not m:
                continue
        m["role"] = z.role
        m["is_logo"] = is_logo
        m["window"] = win
        out[z.role] = m
    return out


def apply_measured(brief: Brief, measured: dict[str, dict]) -> Brief:
    """Fold measured metrics into zone rects/styles (what strip + manifest use)."""
    for z in brief.zones:
        m = measured.get(z.role)
        if not m:
            continue
        x0, y0, x1, y1 = m["bbox"]
        w, h = x1 - x0, y1 - y0
        if not m.get("is_logo") and z.role != "cta":
            w = w * 1.05 + 0.002  # slack so re-rendered glyphs never wrap
        z.rect = [x0, y0, w, h]
        st = dict(z.style or {})
        if m.get("color") and not m.get("is_logo"):
            st["color"] = m["color"]
        if m.get("size") and not m.get("is_logo"):
            st["size"] = m["size"]
        st["padding"] = 0 if z.role != "cta" else st.get("padding")
        st["lineHeight"] = 1
        st["measured"] = True
        if z.role == "cta":
            st["draw_bg"] = False  # baked pill stays in the design raster
        fp = m.get("font_path")
        if fp:
            from pathlib import Path

            st["font_family"] = Path(fp).stem
            st["font_src"] = "/files/fonts/" + Path(fp).name
        z.style = st
    return brief


def mark_replaceable(brief: Brief, plan: dict[str, dict]) -> Brief:
    """Stamp each zone with the replacement decision (strip/manifest follow it)."""
    for z in brief.zones:
        p = plan.get(z.role) or {}
        st = dict(z.style or {})
        st["replace"] = bool(p.get("replace"))
        st["replace_reason"] = p.get("reason", "")
        z.style = st
    return brief


def asset_ink_box(png_path: str) -> tuple[float, float, float, float]:
    """Ink bbox of an asset as fractions of the asset image (transparent padding)."""
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
