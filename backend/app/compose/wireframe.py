"""Render the wireframe — the super-detailed layout spec sent WITH the refs so
the image model realizes exactly what we expect (consistency). Judge compares
the result against this same wireframe."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..models import Brief

_ROLE_COLOR = {
    "headline": (220, 38, 38),
    "sub": (217, 119, 6),
    "body": (37, 99, 235),
    "cta": (22, 163, 74),
    "logo": (147, 51, 234),
    "logo_footer": (147, 51, 234),
    "footer": (147, 51, 234),
    "bg": (100, 116, 139),
    "photo": (100, 116, 139),
    "ui": (8, 145, 178),
    "charm": (202, 138, 4),
    "bloom": (236, 72, 153),
    "accent": (100, 116, 139),
}

_RATIO = {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}


def _font(size: int):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def build_wireframe_png(brief: Brief, out_path: Path) -> str:
    """Draw the expected layout: every zone's rect, role and exact content."""
    W, H = _RATIO.get(brief.ratio, (1024, 1024))
    im = Image.new("RGB", (W, H), (248, 250, 252))
    d = ImageDraw.Draw(im)
    f_role = _font(max(14, W // 48))
    f_txt = _font(max(12, W // 60))
    f_note = _font(max(11, W // 70))

    for z in brief.zones:
        x, y, w, h = [float(v) for v in z.rect]
        x0, y0, x1, y1 = x * W, y * H, (x + w) * W, (y + h) * H
        color = _ROLE_COLOR.get(z.role.replace("text_", ""), (100, 116, 139))
        d.rectangle([x0, y0, x1, y1], outline=color, width=3)
        # corner ticks
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            d.rectangle([cx - 4, cy - 4, cx + 4, cy + 4], fill=color)
        label = f" {z.role} "
        d.text((x0 + 6, y0 + 6), label, font=f_role, fill=(255, 255, 255))
        d.rectangle([x0 + 4, y0 + 4, x0 + 8 + f_role.getlength(label), y0 + 10 + f_role.size], fill=color)
        d.text((x0 + 6, y0 + 6), label, font=f_role, fill=(255, 255, 255))
        content = (z.content or "").strip()
        if content:
            # wrap content into the box
            words = content.split()
            lines, cur = [], ""
            for wd in words:
                t = (cur + " " + wd).strip()
                if f_txt.getlength(t) > (x1 - x0 - 14) and cur:
                    lines.append(cur)
                    cur = wd
                else:
                    cur = t
            if cur:
                lines.append(cur)
            ty = y0 + 10 + f_role.size + 6
            for ln in lines[:6]:
                d.text((x0 + 8, ty), ln, font=f_txt, fill=(30, 41, 59))
                ty += f_txt.size + 3
        d.text((x0 + 6, y1 - f_note.size - 6), f"rect {x:.2f},{y:.2f},{w:.2f},{h:.2f}", font=f_note, fill=(148, 163, 184))

    d.text((12, H - 28), f"WIREFRAME — realize this layout exactly · {brief.ratio} · {brief.copy.headline[:40]}", font=f_note, fill=(71, 85, 105))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return str(out_path)
