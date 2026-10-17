import json
import re

from .. import llm
from ..models import CopyBlock, Grammar

COPY_SYSTEM = """You are a witty sales creative for brand ads. Given a use-case and brand grammar, output JSON:
{"variants":[{"id": str, "tone": str, "archetype": str, "copy": {"headline": str, "sub": str, "body": [str], "cta": str}}],
 "concept_notes": str}
Rules:
- headline <= 8 words, punchy, quirky sales energy. sub <= 12 words. body 2-5 short bullets <= 8 words each. cta <= 4 words.
- archetype is one of the recipe names provided (or closest fit).
- copy must be exact final strings: no placeholder, no lorem, no brackets.
- Match the brand voice and respect donts."""


def generate_copy(use_case: str, grammar: Grammar, n: int = 4) -> list[dict]:
    recipes = [r.model_dump() for r in grammar.recipes]
    payload = {
        "use_case": use_case,
        "brand": grammar.brand,
        "palette": grammar.palette,
        "voice_donts": grammar.donts[:12],
        "recipes": [{"id": r["id"], "name": r["name"], "intent": r["intent"]} for r in recipes],
    }
    raw = llm.chat_text(COPY_SYSTEM, json.dumps(payload, ensure_ascii=False), model="pro", json_mode=True)
    data = _parse(raw)
    variants = data.get("variants", [])[:n]
    while len(variants) < n:
        base = variants[0] if variants else {"id": f"v{len(variants)+1}", "tone": "confident", "archetype": recipes[0]["name"] if recipes else "showcase", "copy": {"headline": use_case[:40], "sub": "", "body": [], "cta": "Learn more"}}
        clone = json.loads(json.dumps(base))
        clone["id"] = f"{base.get('id','v')}_{len(variants)+1}"
        variants.append(clone)
    for i, v in enumerate(variants):
        v.setdefault("id", f"v{i+1}")
        c = v.get("copy") or {}
        v["copy"] = {
            "headline": c.get("headline", use_case),
            "sub": c.get("sub", ""),
            "body": c.get("body", []),
            "cta": c.get("cta", "Learn more"),
        }
    return variants


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


def copy_block(v: dict) -> CopyBlock:
    return CopyBlock.model_validate(v.get("copy", {}))
