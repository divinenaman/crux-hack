import json
import re

from .. import llm
from ..models import Asset


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


VERIFY_SYSTEM = """Verify an asset record against its image and brand rules. Output ONLY JSON:
{"ok": bool, "issues": [str], "use_cases": [str], "mismatches": [str]}
- issues = file/quality problems visible (washed out, clipped edges, wrong crop, label bleeding).
- use_cases = 2-5 short usage scenarios (e.g. "dark-mode hero accent").
- mismatches = conflicts with the provided brand rules or folder class (e.g. white logo under light-mode folder)."""


def verify_asset_batch(brand_id: str, assets: list[Asset], rules_blob: str) -> list[Asset]:
    if not assets:
        return assets
    parts = [{"type": "text", "text": VERIFY_SYSTEM}, {"type": "text", "text": "BRAND RULES:\n" + rules_blob}]
    for i, a in enumerate(assets[:8]):
        parts.append({"type": "text", "text": f"ASSET {i}: id={a.id} name={a.name} kind={a.kind} folder='{a.folder}' tags={a.tags} colors={a.colors}"})
        if a.png:
            try:
                parts.append(llm.img_part(a.png, detail="low"))
            except Exception:
                pass
    try:
        raw = llm.chat_vision("", parts, model="flash", json_mode=True)
        items = _parse(raw)
    except Exception:
        return assets
    issues = items.get("issues", []) if isinstance(items.get("issues"), list) else []
    uses = items.get("use_cases", []) if isinstance(items.get("use_cases"), list) else []
    mism = items.get("mismatches", []) if isinstance(items.get("mismatches"), list) else []
    for a in assets[:8]:
        a.quality = dict(a.quality or {})
        if issues:
            a.quality.setdefault("issues", [])
            a.quality["issues"] = list(dict.fromkeys((a.quality.get("issues") or []) + [str(x) for x in issues]))[:6]
            a.quality["ok"] = not a.quality["issues"]
        if uses:
            a.use_cases = list(dict.fromkeys(a.use_cases + [str(u).lower() for u in uses]))[:10]
        if mism:
            a.mismatches = list(dict.fromkeys(a.mismatches + [str(m) for m in mism]))[:8]
    return assets
