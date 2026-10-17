import json
import random
import re

from .. import llm, store
from ..models import Cohort, CopyBlock, Grammar, SlotFill, Zone

ANGLES = [
    "witty_pain_point",
    "aspirational_gain",
    "social_proof",
    "playful_metaphor",
    "bold_contrast",
    "warm_reassurance",
]

PLAN_SYSTEM = """You are a creative director (deep thinking) planning DISTINCT ad concepts — one per idea cohort.
top_idea_cohorts = N. Each cohort MUST tell a different story with its own asset cohort. Backgrounds must not look alike.
For EVERY cohort you MUST output the story/idea you want the image to show AND the exact set of asset_ids to use.
Output ONLY JSON:
{"cohorts": [{
  "id": str, "name": str, "angle": str, "story": str, "idea": str, "color_story": str,
  "recipe_id": str, "boldness": "bold"|"balanced"|"simple",
  "copy": {"headline": str, "sub": str, "body": [str], "cta": str},
  "slots": [{"role": str, "asset_id": str, "why": str, "placement": str}],
  "zones": [{"role": str, "rect": [x,y,w,h] 0..1 fractions, "text_free": bool, "content": str, "style": {}}]
}]}

HARD RULES:
1. Each cohort uses 4-8 DISTINCT assets. Every slot MUST have:
   - why: what the asset MEANS (its semantics), how it JELLS with the other chosen assets, and why its COLOURS fit this story.
   - placement: exactly where it goes and what it does in the composition.
2. Cross-cohort: do not reuse an asset across cohorts unless it is the logo. Backgrounds/templates MUST differ per cohort.
3. color_story: name the lead colour + accents and the mood.
4. recipe_id: pick from provided recipes. Follow techniques + context rules + logo colourway pairs + donts.
5. copy: exact final strings. headline <= 8 words. NO placeholders.
6. zones: full layout in canvas fractions. headline/sub/body/cta/logo_footer zones required.
7. Pick assets by MEANING first (lexicon semantics), then colour harmony. Deliberately vary lead shapes and motifs per cohort.
8. ONLY use asset_ids from the provided asset_pool (optionally scoped to a folder)."""


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


def _catalog_digest(brand_id: str, folder: str = "") -> list[dict]:
    out = []
    for a in store.query_assets(brand_id, folder=folder):
        if not a.directly_usable or a.kind == "doc":
            continue
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "kind": a.kind,
                "folder": a.folder,
                "semantic": a.semantic,
                "tags": a.tags[:6],
                "colors": a.colors[:4],
                "use_cases": a.use_cases[:5],
            }
        )
    return out


def plan_cohorts(brand_id: str, use_case: str, grammar: Grammar, n: int = 4, seed: int | None = None, folder: str = "") -> list[Cohort]:
    rng = random.Random(seed)
    pool = _catalog_digest(brand_id, folder)
    rng.shuffle(pool)
    angles = ANGLES[:]
    rng.shuffle(angles)

    recipes = [{"id": r.id, "name": r.name, "intent": r.intent, "slots": [s.role for s in r.slots], "boldness": r.boldness} for r in grammar.recipes]
    payload = {
        "use_case": use_case,
        "n": n,
        "folder_scope": folder or "(all asset classes)",
        "assigned_angles": {str(i + 1): angles[i % len(angles)] for i in range(n)},
        "brand": grammar.brand,
        "palette": grammar.palette,
        "lexicon": [{"name": e.name, "semantic": e.semantic, "family": e.family} for e in grammar.lexicon[:40]],
        "recipes": recipes,
        "techniques": [t.model_dump() for t in grammar.techniques[:8]],
        "context_rules": [c.model_dump() for c in grammar.context_rules[:8]],
        "logo_rules": grammar.logo_rules,
        "safe_zones": grammar.safe_zones,
        "donts": [d for d in grammar.donts if not d.startswith("doc_page")][:12],
        "asset_pool": pool,
    }
    raw = llm.chat_text(PLAN_SYSTEM, json.dumps(payload, ensure_ascii=False), model="pro", json_mode=True)
    data = _parse(raw)
    valid = {a["id"] for a in pool}

    cohorts: list[Cohort] = []
    used: set[str] = set()
    for i, c in enumerate(data.get("cohorts", [])[:n]):
        slots = []
        for s in c.get("slots", []):
            aid = s.get("asset_id", "")
            if aid not in valid:
                continue
            if aid in used and "logo" not in s.get("role", ""):
                continue
            used.add(aid)
            slots.append(SlotFill.model_validate(s))
        if len(slots) < 3:
            continue
        c.setdefault("id", f"idea_{i+1}")
        c["copy"] = CopyBlock.model_validate(c.get("copy") or {"headline": use_case[:40], "cta": "Learn more"})
        c["zones"] = [Zone.model_validate(z) for z in c.get("zones", [])]
        c["slots"] = slots
        cohorts.append(Cohort.model_validate({k: c[k] for k in Cohort.model_fields if k in c}))

    while len(cohorts) < n:
        base = cohorts[0] if cohorts else None
        if base is None:
            from .shortlist import candidates_for_role, fill_recipe

            brief_seed = {"copy": CopyBlock(headline=use_case[:40], cta="Learn more")}
            raise ValueError("thinking model returned no usable cohorts for this asset folder")
        clone = base.model_copy(deep=True)
        clone.id = f"idea_{len(cohorts)+1}"
        clone.name = f"{base.name} alt"
        clone.slots = []
        cohorts.append(clone)
    return cohorts[:n]
