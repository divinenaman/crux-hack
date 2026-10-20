"""Background fill — the ONLY job the image model gets.

The layout wireframe (real pieces — assets, logos, text — on a plain canvas)
goes to the image model as a REFERENCE. The prompt describes the entire image
to paint and the clean colour fields to leave where text/pieces sit. The
returned image is the finished background: the real pieces are pasted on top
in code at their recorded positions (canvas size == image size). Nothing to
strip, nothing to measure.
"""
from __future__ import annotations

from pathlib import Path

from .. import llm
from ..brief.placements import _intent_hex
from ..models import Brief

_BG_FORBID = (
    "Draw NO text, letters, numbers, words, logos, watermarks, signatures, brand names, "
    "UI text or captions of any kind — the model gets lettering wrong, and the real copy "
    "is pasted on top afterwards. Everything else is drawable: people, faces, hands, "
    "characters, products, devices, food, plants, rooms, streets, objects and floating "
    "illustration accents."
)


def _size_str(ratio: str) -> str:
    w, h = {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}.get(ratio or "1:1", (1024, 1024))
    return f"{w}x{h}"


def bg_prompt(brief: Brief, grammar=None) -> str:
    lines = [
        "The attached image is a LAYOUT WIREFRAME: the real pieces (logo, text blocks, "
        "decorative elements) placed on a plain canvas. Use it as the composition reference.",
        f"Paint the ENTIRE canvas as a full scene — the world around the pasted pieces: {brief.bg_story or brief.idea or brief.color_story}",
        "Leave each area listed below as a CLEAN FLAT COLOUR FIELD so the pasted piece "
        "reads on it (everything else: full artwork, no empty gaps):",
    ]
    for i, f in enumerate(brief.bg_fields or []):
        x, y, w, h = [round(float(v), 2) for v in f.rect]
        col = f.color or _intent_hex(f.intent, "") or ""
        lines.append(f"- field {i + 1} at x={x} y={y} w={w} h={h}: {f.intent or 'flat field'}{f' (exactly {col})' if col else ''}. {f.why}")
    if grammar and getattr(grammar, "palette", None):
        pal = ", ".join(f"{p.get('name', '')} {p.get('hex', '')}".strip() for p in grammar.palette[:8])
        lines.append(f"Brand palette only: {pal}.")
    lines.append(_BG_FORBID)
    return "\n".join(lines)


def fill_background(brief: Brief, out_path: Path | str, brand_id: str = "", workdir: Path | None = None) -> tuple[str, str, str]:
    """Wireframe (reference) → the model paints the whole background image.

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
