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
{"kind": "text"|"visual"|"both"|"assets",
 "text_changes": [{"role": "headline"|"sub"|"body"|"cta", "content": str}],
 "visual_prompt": str,
 "rects": [[x,y,w,h] 0..1 fractions],
 "asset_adds": [{"query": str, "role": str, "rect": [x,y,w,h] 0..1 fractions}]}
Rules:
- text_changes ONLY when the user wants copy (headline/sub/body/cta) changed. content = exact final string. body content = the full joined body text.
- visual_prompt ONLY for pixel changes to the artwork (colour, shape, background). Must forbid adding text/logos.
- rects = regions to repaint (for mask), fractions of canvas. Empty if global.
- asset_adds = place KNOWN brand assets (logos, charms, product shots, icons) from the brand catalog. query = short search phrase describing the wanted asset (e.g. "beekeeper", "coins", "logo white"). role = its role (logo/charm/bg/accent/ui). rect = where it goes on canvas. Prefer asset_adds over redraw whenever the user asks to add/put/place/swap a brand thing.
- kind=text when ONLY copy changes. kind=visual when ONLY pixels change. kind=assets when ONLY known assets are placed. kind=both otherwise."""


def _heuristic_edit(instruction: str) -> dict:
    """Regex fallback when the thinking model is unreachable — keeps the edit
    workflow functional (and instant) for text / asset-add / visual requests."""
    t = instruction.strip()
    low = t.lower()
    out: dict = {"kind": "visual", "visual_prompt": t, "rects": [], "text_changes": [], "asset_adds": []}

    m = re.search(r"(headline|sub(?:head)?|body|cta)\b[^'\"’]*['\"’]([^'\"’]+)['\"’]", t, re.I)
    if m and re.search(r"\b(change|set|update|replace|rewrite|write|rename)\b", low):
        role = m.group(1).lower().replace("subhead", "sub")
        out["text_changes"] = [{"role": role, "content": m.group(2)}]
        out["kind"] = "text"
        return out

    if re.search(r"\b(add|put|place|insert|drop)\b", low):
        q = re.sub(r"^.*\b(?:add|put|place|insert|drop)\s+(?:the\s+|a\s+)?", "", low).strip(" .!")
        q = re.split(r"\s+(?:on|in|at|to|near|beside|under|over|next)\b", q)[0].strip() or "accent"
        rect = [0.35, 0.35, 0.3, 0.3]
        if re.search(r"top[- ]?right", low):
            rect = [0.62, 0.05, 0.3, 0.3]
        elif re.search(r"top[- ]?left", low):
            rect = [0.05, 0.05, 0.3, 0.3]
        elif re.search(r"bottom[- ]?right", low):
            rect = [0.62, 0.6, 0.3, 0.3]
        elif re.search(r"bottom[- ]?left", low):
            rect = [0.05, 0.6, 0.3, 0.3]
        elif re.search(r"\bcenter|middle\b", low):
            rect = [0.3, 0.3, 0.4, 0.4]
        out["asset_adds"] = [{"query": q, "role": "accent", "rect": rect}]
        out["kind"] = "assets"
        out["visual_prompt"] = ""
        return out

    return out


def classify_edit(instruction: str, manifest: dict) -> dict:
    zones = []
    for l in manifest.get("layers", []):
        if l.get("type") == "text":
            zones.append({"role": l.get("role"), "content": l.get("content"), "bbox": l.get("bbox")})
    payload = {"instruction": instruction, "text_layers": zones, "canvas": manifest.get("canvas")}
    try:
        raw = llm.chat_text(EDIT_SYSTEM, json.dumps(payload, ensure_ascii=False), model="pro", json_mode=True)
        data = _parse(raw)
        if not data:
            raise ValueError("empty classify response")
    except Exception:
        data = _heuristic_edit(instruction)
    kind = data.get("kind", "visual")
    if kind not in ("text", "visual", "both", "assets"):
        kind = "visual"
    data["kind"] = kind
    data["text_changes"] = [t for t in data.get("text_changes", []) if isinstance(t, dict) and t.get("content")]
    data["rects"] = [r for r in data.get("rects", []) if isinstance(r, list) and len(r) == 4]
    data["asset_adds"] = [a for a in data.get("asset_adds", []) if isinstance(a, dict) and (a.get("query") or a.get("role"))]
    return data


def rag_assets(brand_id: str, query: str, k: int = 3) -> list:
    """RAG over the indexed catalog — see app.rag.retrieve."""
    from .rag import retrieve

    return retrieve(brand_id, query, k=k)


def apply_asset_adds(manifest: dict, design_src: str, out_path: Path, adds: list[dict], brand_id: str) -> str:
    """RAG-retrieve each requested asset and paste it into the design (exact
    brand pixels, aspect-fit, 2px-feathered edge). Adds image layers so the
    pasted assets stay draggable in the canvas."""
    from PIL import Image, ImageFilter

    from . import store
    from .imutil import ensure_raster

    im = Image.open(design_src).convert("RGBA")
    W, H = im.size
    added = []
    for add in adds:
        query = add.get("query") or add.get("role") or ""
        role = add.get("role") or "accent"
        cands = rag_assets(brand_id, query, k=1) or rag_assets(brand_id, role, k=1)
        if not cands:
            continue
        asset = cands[0]
        rect = add.get("rect") or [0.35, 0.35, 0.3, 0.3]
        try:
            x, y, w, h = [float(v) for v in rect]
        except Exception:
            x, y, w, h = 0.35, 0.35, 0.3, 0.3
        x, y = max(0.0, min(0.95, x)), max(0.0, min(0.95, y))
        w, h = max(0.04, min(1.0 - x, w)), max(0.04, min(1.0 - y, h))
        box = (x * W, y * H, w * W, h * H)
        try:
            art = Image.open(ensure_raster(asset.png)).convert("RGBA")
        except Exception:
            continue
        art.thumbnail((max(8, int(box[2])), max(8, int(box[3]))))
        px = int(box[0] + (box[2] - art.width) / 2)
        py = int(box[1] + (box[3] - art.height) / 2)
        feather = art.split()[3].filter(ImageFilter.GaussianBlur(2))
        im.paste(art, (px, py), feather)
        added.append(
            {
                "type": "image",
                "role": role,
                "src": asset.png,
                "asset_id": asset.id,
                "bbox": [float(px), float(py), float(art.width), float(art.height)],
                "style": {"placed_by": "rag", "why": f"RAG: '{query}' → {asset.name}"},
                "locked": False,
                "baked": False,
                "visible": True,
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out_path)
    manifest["design_src"] = str(out_path)
    for l in manifest.get("layers", []):
        if l.get("role") == "design":
            l["src"] = str(out_path)
    manifest["layers"] = list(manifest.get("layers", [])) + added
    return str(out_path)


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
    if mask_path and Path(mask_path).exists():
        # gemini redraws the whole canvas — composite the original back outside
        # the editable windows so the rest stays pixel-identical (2px feather)
        from .compose.composer import _composite_edit

        _composite_edit(Path(src), png, Path(mask_path), Path(out_path))
    else:
        out_path.write_bytes(png)
    return str(out_path)
