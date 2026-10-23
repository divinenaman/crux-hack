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

from .. import config, llm
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
    from .. import config

    base = {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}.get(ratio or "1:1", (1024, 1024))
    s = config._res_scale()
    w, h = round(base[0] * s / 16) * 16, round(base[1] * s / 16) * 16
    return f"{w}x{h}"


def bg_prompt(brief: Brief, grammar=None) -> str:
    lines = [
        "The attached image is a low-fidelity COMPOSITION MAP (colour-planned positions) for a "
        "PROFESSIONAL advertising image — it is NOT a design to copy or restyle.",
        f"Paint the whole frame as a finished, FULL-BLEED commercial scene — photography or crafted "
        f"illustration grade, styled like premium brand work: {brief.bg_story or brief.idea or brief.color_story}",
        "The brand graphics placed on the map (wordmark, motifs) are REAL and exactly placed here — do "
        "NOT redraw, restyle, move or cover them; the faint dotted frame around an asset is only its slot "
        "marker — never render any dotted/dashed line in your output anywhere.",
        "Real copy gets composited on top later; keep the passages listed below calm.",
    ]
    for i, f in enumerate(brief.bg_fields or []):
        x, y, w, h = [round(float(v), 2) for v in f.rect]
        col = f.color or _intent_hex(f.intent, "") or ""
        lines.append(
            f"- quiet zone {i + 1} at x={x} y={y} w={w} h={h}: stay calm here{f' (lean toward {col})' if col else ''}. "
            "No drawn rectangle, no fill edge — just a serene low-detail passage of scene."
        )
    band_shapes = [
        p for p in (brief.placements or [])
        if p.kind == "shape" and float((p.rect or [0, 0, 0, 0])[2]) * float((p.rect or [0, 0, 0, 0])[3]) >= 0.18
    ]
    for p in band_shapes:
        x, y, w, h = [round(float(v), 2) for v in p.rect]
        col = (p.style or {}).get("fill") or ""
        lines.append(
            f"- colour field {col or 'brand palette'} at x={x} y={y} w={w} h={h}: keep this palette family, "
            "but paint it alive — gradient, texture, light bloom, illustration accents breathing inside."
        )
    lines += [
        "NO OVERLAYS ANYWHERE: never paint a halo, glow, spotlight, bloom, blur veil, smoke wisp, "
        "white or translucent panel/card/box/slab behind or around anything — placed graphics included. "
        "The scene just continues naturally, sharp and clear edge to edge.",
        "Colour anchored zones breathe alive (gradient/texture/light) — they must NOT come out as large "
        "flat solid rectangles, and no other large solid box may appear anywhere in the output.",
        "Anti-slide rules (hard): NOT a slide, poster mock-up, webpage, dashboard or UI frame — no "
        "headers/footers, no frames/borders, no repeated identical cards, no solid rectangles sitting on "
        "empty paper, none of the map's rectangles drawn as literal objects.",
        "If the art style allows text-free decorative calligraphy strokes or ornaments, keep them away from the quiet zones.",
    ]
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
def _calm_zone_words(brief: Brief) -> list[str]:
    """Turn text/CTA placement geometry into verbal 'keep this quiet' hints."""
    named: list[str] = []
    for p in brief.placements:
        if p.kind not in ("text",) and not str(getattr(p, "role", "") or "").endswith("cta"):
            continue
        x, y, w, h = [float(v) for v in (p.rect or [0, 0, 0, 0])]
        cx, cy = x + w / 2, y + h / 2
        vert = "upper" if cy < 0.4 else ("middle" if cy < 0.65 else "lower")
        horz = "left" if cx < 0.4 else ("centre" if cx < 0.62 else "right")
        named.append(f"{vert} {horz}")
    seen, out = set(), []
    for n in named:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _bg_prompt_t2i(brief: Brief, grammar) -> str:
    """Verbal-only scene prompt — NO reference image, so nothing structural is copied."""
    lines = [
        "Paint a finished, FULL-BLEED commercial background — photography or crafted illustration grade, "
        "styled like premium brand work.",
        getattr(brief, "bg_story", "") or str(getattr(brief, "idea", "")),
    ]
    if grammar and getattr(grammar, "palette", None):
        pal = ", ".join(f"{p.get('name', '')} {p.get('hex', '')}".strip() for p in grammar.palette[:8])
        lines.append(f"Use only this brand palette: {pal}.")
    zones = _calm_zone_words(brief)
    if zones:
        lines.append(
            "Keep the " + ", ".join(zones) + " passages of the frame visually CALM — low detail, soft light or "
            "negative space there (headline and sub copy land on top afterwards); never place focal subjects or "
            "busy texture in those passages."
        )
    lines += [
        getattr(brief, "color_story", ""),
        _BG_FORBID,
    ]
    return "\n".join(x for x in lines if x and x.strip())


def fill_background(brief: Brief, out_path: Path | str, brand_id: str = "", workdir: Path | None = None) -> tuple[str, str, str]:
    """Reference wireframe (edit mode) or verbal-only prompt (t2i mode) → the model paints the background.

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
    raw: bytes
    if config.IMAGE_FILL_MODE == "t2i":
        # text-to-image: no pixel reference at all — any structured map (dashes, ghosts, bands)
        # gets copied literally by edit models, so the geometry guidance stays verbal only
        prompt = _bg_prompt_t2i(brief, grammar)
        size = _size_str(getattr(brief, "ratio", "1:1"))
        raw = llm.generate_image(prompt, size=size, model=config.IMAGE_FILL_T2I_MODEL or None)
    else:
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
