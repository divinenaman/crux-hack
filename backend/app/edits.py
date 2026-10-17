import json
import re
from pathlib import Path

from . import llm
from .models import Brief, Manifest


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


EDIT_SYSTEM = """You classify a user's edit request on a layered ad (stripped design + live text/logo layers).
Output ONLY JSON:
{"kind": "text"|"visual"|"both",
 "text_changes": [{"role": "headline"|"sub"|"body"|"cta", "content": str}],
 "visual_prompt": str,
 "rects": [[x,y,w,h] 0..1 fractions]}
Rules:
- text_changes ONLY when the user wants copy (headline/sub/body/cta) changed. content = exact final string. body content = the full joined body text.
- visual_prompt ONLY for pixel changes to the artwork (colour, shape, background). Must forbid adding text/logos.
- rects = regions to repaint (for mask), fractions of canvas. Empty if global.
- kind=text when ONLY copy changes (no image work). kind=visual when ONLY pixels change. kind=both otherwise."""


def classify_edit(instruction: str, manifest: dict) -> dict:
    zones = []
    for l in manifest.get("layers", []):
        if l.get("type") == "text":
            zones.append({"role": l.get("role"), "content": l.get("content"), "bbox": l.get("bbox")})
    payload = {"instruction": instruction, "text_layers": zones, "canvas": manifest.get("canvas")}
    raw = llm.chat_text(EDIT_SYSTEM, json.dumps(payload, ensure_ascii=False), model="pro", json_mode=True)
    data = _parse(raw)
    kind = data.get("kind", "visual")
    if kind not in ("text", "visual", "both"):
        kind = "visual"
    data["kind"] = kind
    data["text_changes"] = [t for t in data.get("text_changes", []) if isinstance(t, dict) and t.get("content")]
    data["rects"] = [r for r in data.get("rects", []) if isinstance(r, list) and len(r) == 4]
    return data


def load_manifest(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def save_manifest(path: str | Path, data: dict) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return str(p)


def apply_text_changes(manifest: dict, changes: list[dict]) -> dict:
    by_role = {c.get("role"): c.get("content", "") for c in changes}
    for l in manifest.get("layers", []):
        if l.get("type") == "text" and l.get("role") in by_role:
            l["content"] = by_role[l["role"]]
    return manifest


def design_path_of(manifest: dict) -> str:
    return manifest.get("design_src") or next(
        (l.get("src") for l in manifest.get("layers", []) if l.get("role") == "design"), ""
    )


def apply_visual_edit(manifest: dict, src: str, out_path: Path, visual_prompt: str, rects: list[list[float]], brief: Brief | None = None) -> str:
    from PIL import Image, ImageDraw

    from .compose import prompts as compose_prompts

    prompt = (
        f"Surgical artwork edit. {visual_prompt}\n"
        "Do NOT add any text, letters, numbers, logos or watermarks — text and logo are separate live layers.\n"
        "Keep everything outside the edited region pixel-identical."
    )
    mask_path = None
    if rects:
        im = Image.open(src)
        w, h = im.size
        mask = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(mask)
        for x, y, rw, rh in rects:
            pad = 0.03
            x0 = max(0.0, x - pad) * w
            y0 = max(0.0, y - pad) * h
            x1 = min(1.0, x + rw + pad) * w
            y1 = min(1.0, y + rh + pad) * h
            draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 0))
        mask_path = out_path.with_name(f"{out_path.stem}_mask.png")
        mask.save(mask_path)
    ratio = (brief.ratio if brief else "1:1")
    png = llm.edit_image(prompt, src, size=compose_prompts.size_for(ratio), mask_path=mask_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return str(out_path)
