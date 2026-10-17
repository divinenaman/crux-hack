import json
import re

from .. import llm
from ..models import Brief, Grammar
from ..compose.prompts import build_placement_tune_payload

TUNE_SYSTEM = """You fine-tune text/logo placement for an ad whose artwork has ALL text and logo removed (clean design layer).
You see the stripped design and the proposed text zones. Fix ONLY rect and font-size so text sits inside the visible cards/areas with good margins and hierarchy.
Output ONLY JSON: {"zones":[{"role": str, "rect": [x,y,w,h] 0..1 fractions, "style": {"size": number, "weight": number, "color": str, "align": "left"|"center"}}]}
Rules:
- rect must cover where the text should render on the stripped art (inside the visible empty card/area for that role).
- headline size > subhead size > body size. CTA rect should match the visible button pill.
- Keep rects non-overlapping. Move at most 8 percentage points from current rects unless clearly wrong."""


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


def tune_placement(stripped_path: str, brief: Brief) -> Brief:
    payload = build_placement_tune_payload(brief)
    parts = [
        {"type": "text", "text": TUNE_SYSTEM},
        {"type": "text", "text": "PROPOSED ZONES:\n" + json.dumps(payload, ensure_ascii=False)},
        {"type": "text", "text": "STRIPPED DESIGN (no text, no logo):"},
        llm.img_part(stripped_path, detail="high"),
    ]
    raw = llm.chat_vision("", parts, model="flash", json_mode=True)
    data = _parse(raw)
    by_role = {z.get("role"): z for z in data.get("zones", []) if isinstance(z, dict)}
    for z in brief.zones:
        adj = by_role.get(z.role)
        if not adj:
            continue
        rect = adj.get("rect")
        if isinstance(rect, list) and len(rect) == 4 and all(isinstance(v, (int, float)) for v in rect):
            z.rect = [max(0.0, min(1.0, float(v))) for v in rect]
        style = adj.get("style") or {}
        if style:
            z.style = {**z.style, **{k: v for k, v in style.items() if v is not None}}
    return brief
