"""Background fill — the ONLY job the image model gets.

The transparent layout reference (real pieces — assets, logos, text, and shapes
in their final positions and colours) goes to the image model. The prompt describes
the background scene to paint around those pieces. The
returned image is the finished background: the real pieces are pasted on top
in code at their recorded positions (canvas size == image size). Nothing to
strip, nothing to measure.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import config, llm
from ..brief.placements import _intent_hex, is_dark
from ..layout.canvas import DEFAULT_TEXT_COLOR
from ..models import Brief

_BG_FORBID = (
    "ABSOLUTE RULE — NO TEXT OF ANY KIND: zero letters, zero digits, zero words, zero brand names, "
    "zero logos, zero watermarks, zero signatures, zero UI labels, zero captions — not even one "
    "character anywhere in the image. The real copy is composited on top in code; any text you "
    "paint will collide with it and ruin the ad. Render ONLY pure visual scene — people, objects, "
    "textures, light, colour, abstract shapes."
)


def _size_str(ratio: str) -> str:
    from .. import config

    base = {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}.get(ratio or "1:1", (1024, 1024))
    s = config._res_scale()
    w, h = round(base[0] * s / 16) * 16, round(base[1] * s / 16) * 16
    return f"{w}x{h}"


def bg_prompt(brief: Brief, grammar=None) -> str:
    lines = [
        "BACKGROUND ONLY. Use the attached transparent layout image as a spatial and visual guide. "
        "Create one coherent, polished campaign scene that complements the visible brand imagery. "
        "The application will composite the exact foreground over your result.",
        "Paint the transparent areas only. Keep all foreground placement areas clear; never create "
        "a second copy of any visible element. Preserve calm, uncluttered negative space where copy sits.",
    ]
    for p in brief.placements or []:
        x, y, w, h = [round(float(v), 3) for v in p.rect]
        st = p.style or {}
        if p.kind == "text":
            ink = st.get("color") or DEFAULT_TEXT_COLOR
            if ink.upper() != "#FFFFFF":
                lines.append(
                    f"Keep the copy-safe area at x={x}, y={y}, w={w}, h={h} and a small margin "
                    "bright, smooth, and warm ivory. This is mandatory for legibility; no dark "
                    "imagery, shadows, stars, objects, or strong texture in this area."
                )
            else:
                lines.append(
                    f"Keep the area at x={x}, y={y}, w={w}, h={h} dark and visually quiet for "
                    "the white foreground copy."
                )
        elif p.kind == "image":
            lines.append(
                f"Leave the mapped image area at x={x}, y={y}, w={w}, h={h} visually quiet; "
                "the exact image is composited by the application."
            )
    for i, f in enumerate(brief.bg_fields or []):
        x, y, w, h = [round(float(v), 2) for v in f.rect]
        col = f.color or _intent_hex(f.intent, "") or ""
        tone = "deep navy" if col and is_dark(col) else "light warm neutral"
        lines.append(
            f"Backing field at x={x}, y={y}, w={w}, h={h}: keep it {tone} and low-detail."
        )
    lines += [
        "Contrast is mandatory: dark foreground copy always needs a light background; white copy "
        "needs a dark one. Prioritize readability over dramatic lighting. Keep one scene, avoid "
        "lettering and logos, and let the mapped foreground remain dominant.",
    ]
    if grammar and getattr(grammar, "palette", None):
        pal = ", ".join(p.get("name", "") for p in grammar.palette[:8] if p.get("name"))
        if pal:
            lines.append(f"Coordinate with these brand palette names: {pal}.")
    lines.append(_BG_FORBID)
    return "\n".join(lines)


def fill_background(
    brief: Brief,
    out_path: Path | str,
    brand_id: str = "",
    workdir: Path | None = None,
    on_prepared: Callable[[str, str], None] | None = None,
) -> tuple[str, str, str]:
    """Send the complete transparent layout reference; paint the background around it.

    Returns (bg_path, fill_prompt, wireframe_path)."""
    from ..layout.canvas import render_layout

    workdir = Path(workdir) if workdir else Path(out_path).parent
    workdir.mkdir(parents=True, exist_ok=True)
    wire = workdir / f"{Path(out_path).stem}_wire.png"
    render_layout(brief, wire, brand_id=brand_id, mode="proof")
    grammar = None
    try:
        from .. import store

        grammar = store.load_grammar(brand_id) if brand_id else None
    except Exception:
        pass
    prompt = bg_prompt(brief, grammar)
    if on_prepared:
        on_prepared(prompt, str(wire))
    raw = llm.edit_image(prompt, wire, size=_size_str(getattr(brief, "ratio", "1:1")), strength=0.8)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    return str(out), prompt, str(wire)


def composite_back(src_path: Path | str, edited_png: bytes, mask_path: Path | str, out_path: Path | str) -> None:
    """Enforce 'everything outside the edit window pixel-identical' in code.

    The image model drifts whole-canvas even with a perfect mask — so we keep the
    original everywhere except inside the masked windows (2px feather)."""
    from io import BytesIO

    from PIL import Image, ImageFilter

    src = Image.open(src_path).convert("RGBA")
    edt = Image.open(BytesIO(edited_png)).convert("RGBA")
    if edt.size != src.size:
        edt = edt.resize(src.size)
    mask = Image.open(mask_path).convert("RGBA")
    keep = mask.split()[3].filter(ImageFilter.GaussianBlur(2))  # 255 = keep original
    out = Image.composite(src, edt, keep)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.convert("RGB").save(out_path)
