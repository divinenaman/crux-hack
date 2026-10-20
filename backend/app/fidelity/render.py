"""Deterministic text/logo overlay composite + screenshot critique loop.

The replace pass gives us live layers at measured bboxes; this module fits the
copy into each box with real font metrics (never crops), renders the composite,
then shows the SCREENSHOT to the vision model and applies its size/position
corrections — the "look at the canvas and adjust" loop a designer does.
"""
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, llm
from ..imutil import ensure_raster
from ..models import Manifest
from .typo import fit_text_block, load_font, resolve_font_path

CRITIQUE_SYSTEM = """You review the text overlays of an ad composited on its design.
For each text block you get: role, intended copy, and its box [x,y,w,h] in px on a WxH canvas.
Look at the screenshot and report ONLY blocks that need changes:
- clipped at an edge of its box, or overflowing its box
- too small / too large for the design hierarchy
- badly positioned vs the composition (drifting off its zone)
Reply ONLY JSON:
{"fixes": [{"role": str, "size_scale": float, "dx": float, "dy": float, "grow": float}]}
size_scale multiplies font size (0.5..1.5, 1.0 = keep).
dx/dy shift the box as fractions of canvas W/H (0 = keep, |x| <= 0.1).
grow expands the box as a fraction of canvas (0..0.15 positive = bigger, negative = tighter).
Only list blocks that need changes — empty list if everything fits well."""


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        try:
            return json.loads(m.group(0)) if m else {}
        except Exception:
            return {}


def _font_path(style: dict) -> str | None:
    src = (style or {}).get("font_src") or ""
    if src.startswith("/files/"):
        p = config.WORKSPACE / src[len("/files/") :]
        if p.exists():
            return str(p)
    return resolve_font_path((style or {}).get("font") or "")


def bake_text_styles(manifest: Manifest) -> None:
    """Fit every live text layer's copy into its box (real metrics, no crop)."""
    for l in manifest.layers:
        if l.type != "text" or l.baked or not (l.content or "").strip():
            continue
        _, _, w, h = [float(v) for v in l.bbox]
        st = dict(l.style or {})
        fp = _font_path(st)
        weight = int(st.get("weight") or 400)
        multiline = l.role != "cta" and (len(l.content) > 18 or "\n" in l.content)
        fit = fit_text_block(fp, l.content, w, h, multiline=multiline, weight=weight)
        scale = float(st.get("size_scale") or 1.0)
        if abs(scale - 1.0) > 0.02:  # critique asked for a specific scale
            fit = fit_text_block(fp, l.content, w, h, multiline=multiline, weight=weight, force_size=int(fit["size"] * scale))
        st["size"] = fit["size"]
        st["lines"] = fit["lines"]
        st["lineGap"] = fit["line_gap"]
        st["lineHeight"] = fit["line_gap"]
        st["padding"] = 0
        l.style = st


def render_composite(design_png: str, manifest: Manifest, out_png: str) -> str:
    """Composite live layers (shape/image/text) onto the background raster —
    what the canvas shows."""
    base = Image.open(ensure_raster(design_png)).convert("RGBA")
    W = int(float(manifest.canvas.get("w") or base.width))
    H = int(float(manifest.canvas.get("h") or base.height))
    if base.size != (W, H):
        base = base.resize((W, H), Image.LANCZOS)  # model returns native size; layers are canvas-space
    for l in manifest.layers:
        if l.visible is False or l.role in ("design", "background"):
            continue
        x, y, w, h = [float(v) for v in l.bbox]
        st = l.style or {}
        d = ImageDraw.Draw(base)
        if l.type == "shape":
            fill = st.get("fill") or "#0b1a3a"
            stroke = st.get("stroke") or None
            if isinstance(stroke, str) and stroke.strip().lower() in ("none", "null", "transparent"):
                stroke = None
            if isinstance(fill, str) and fill.strip().lower() in ("none", "null", "transparent"):
                fill = None
            width = int(st.get("strokeWidth") or 0)
            shape = str(st.get("shape") or "rect").lower()
            if shape == "circle":
                d.ellipse([x, y, x + w, y + h], fill=fill, outline=stroke, width=width)
            elif shape == "pill":
                d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=fill, outline=stroke, width=width)
            else:
                r = float(st.get("radius") or 0)
                if r > 0:
                    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=stroke, width=width)
                else:
                    d.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=width)
            continue
        if l.type == "image" and l.src:
            try:
                art = Image.open(ensure_raster(l.src)).convert("RGBA")
            except Exception:
                continue
            art = art.resize((max(1, int(w)), max(1, int(h))))
            base.alpha_composite(art, (int(x), int(y)))
            continue
        if l.type != "text" or not (l.content or "").strip():
            continue
        if l.role == "cta" and st.get("draw_bg"):
            d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=st.get("bg_color") or "#0b1a3a")
        size = int(st.get("size") or 24)
        gap = float(st.get("lineGap") or st.get("lineHeight") or 1.15)
        lines = st.get("lines") or [l.content]
        f = load_font(_font_path(st), size, int(st.get("weight") or 400))
        try:
            asc, desc = f.getmetrics()
        except Exception:
            asc, desc = int(size * 0.8), int(size * 0.25)
        total_h = (len(lines) - 1) * size * gap + (asc + desc)
        vtop = y + max(0.0, (h - total_h) / 2)  # vertically centred in the measured box
        align = st.get("align") or ("center" if l.role == "cta" else "left")
        for i, ln in enumerate(lines):
            lw = f.getlength(ln)
            tx = x if align == "left" else (x + (w - lw) / 2 if align == "center" else x + w - lw)
            ty = vtop + i * size * gap + max(0.0, (size * gap - (asc + desc)) / 2)
            d.text((tx, ty), ln, font=f, fill=st.get("color") or "#000856", anchor="la")
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out)
    return str(out)


def critique_overlays(png: str, manifest: Manifest) -> list[dict]:
    """Screenshot → per-block corrections (size/position). kimi-latest = best spatial judge."""
    W = float(manifest.canvas.get("w") or 1024)
    H = float(manifest.canvas.get("h") or 1024)
    blocks = [
        {"role": l.role, "text": l.content, "box": [round(v) for v in l.bbox]}
        for l in manifest.layers
        if l.type == "text" and not l.baked and (l.content or "").strip()
    ]
    if not blocks:
        return []
    try:
        raw = llm.chat_vision(
            CRITIQUE_SYSTEM,
            [
                {"type": "text", "text": f"Canvas {int(W)}x{int(H)}. Text blocks:\n{json.dumps(blocks)}"},
                llm.img_part(png, detail="high"),
            ],
            model="kimi-latest",
            json_mode=True,
            timeout=90.0,
            attempts=2,
        )
    except Exception:
        return []
    data = _parse(raw)
    return [f for f in data.get("fixes", []) if isinstance(f, dict) and f.get("role")]


def apply_overlay_fixes(manifest: Manifest, fixes: list[dict]) -> int:
    W = float(manifest.canvas.get("w") or 1024)
    H = float(manifest.canvas.get("h") or 1024)
    by_role = {l.role: l for l in manifest.layers if l.type == "text"}
    n = 0
    for f in fixes:
        l = by_role.get(str(f.get("role")))
        if not l:
            continue
        x, y, w, h = [float(v) for v in l.bbox]
        dx = max(-0.1, min(0.1, float(f.get("dx") or 0.0)))
        dy = max(-0.1, min(0.1, float(f.get("dy") or 0.0)))
        grow = max(-0.2, min(0.15, float(f.get("grow") or 0.0)))
        ss = max(0.5, min(1.5, float(f.get("size_scale") or 1.0)))
        changed = False
        if dx or dy:
            x, y = x + dx * W, y + dy * H
            changed = True
        if grow:
            x, y, w, h = x - grow * W / 2, y - grow * H / 2, w + grow * W, h + grow * H
            changed = True
        if abs(ss - 1.0) > 0.02:
            st = dict(l.style or {})
            st["size_scale"] = max(0.5, min(1.5, float(st.get("size_scale") or 1.0) * ss))
            l.style = st
            changed = True
        if changed:
            l.bbox = [x, y, w, h]
            n += 1
    return n


def polish_overlays(design_png: str, manifest: Manifest, out_png: str, rounds: int = 2) -> list[str]:
    """fit → render → screenshot critique → adjust, 1–2 rounds. Writes the final composite."""
    notes: list[str] = []
    bake_text_styles(manifest)
    render_composite(design_png, manifest, out_png)
    for i in range(rounds):
        fixes = critique_overlays(out_png, manifest)
        if not fixes:
            notes.append(f"round {i + 1}: overlays clean")
            break
        n = apply_overlay_fixes(manifest, fixes)
        bake_text_styles(manifest)  # refit after box/size changes
        render_composite(design_png, manifest, out_png)
        notes.append(f"round {i + 1}: {n} adjustments [{', '.join(str(f.get('role')) for f in fixes)}]")
    return notes
