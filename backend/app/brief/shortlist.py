import json
import re

from .. import llm, store
from ..models import Asset, Brief, Grammar, Recipe, SlotFill, Zone

FILL_SYSTEM = """You fill a composition recipe's slots with brand assets. Output JSON:
{"fills":[{"role": str, "asset_id": str, "why": str, "placement": str}],
 "zones":[{"role": str, "rect": [x,y,w,h] as 0..1 fractions, "text_free": bool, "content": str, "style": {}}],
 "boldness": "bold"|"balanced"|"simple",
 "violations": [str]}
Rules:
- ONLY use provided asset_ids. Every required slot must get an asset; skip optional slots if nothing fits.
- zones: lay out the canvas. Include zones for headline, body, cta, logo_footer if present in copy.
- text_free=true for body/cta zones (they will be overlaid live). headline text_free=false (rendered in image).
- rect fractions must stay inside Meta safe zones when provided. No overlap of text zones.
- violations = brand-rule risks you cannot satisfy with these assets (empty if fine)."""


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


def candidates_for_role(role: str, assets: list[Asset], grammar: Grammar) -> list[Asset]:
    out = []
    for a in assets:
        if not a.directly_usable or a.kind == "doc":
            continue
        hay = f"{a.kind} {' '.join(a.tags)} {a.semantic} {a.role_hints} {a.name} {a.usage}".lower()
        if role == "bg" and (a.kind == "template" or "bg" in hay or "background" in hay):
            out.append(a)
        elif role in ("bloom", "mask") and (a.kind == "bloom" or "bloom" in hay or "mask" in hay or "crop" in hay):
            out.append(a)
        elif role == "charm" and (a.kind == "charm" or "charm" in hay or "icon" in hay):
            out.append(a)
        elif role == "logo" and (a.kind == "logo" or "logo" in hay or "wordmark" in hay):
            out.append(a)
        elif role == "ui" and (a.kind == "ui-shot" or "screenshot" in hay or "product" in hay):
            out.append(a)
        elif role in ("photo", "illustration") and (a.kind in ("illustration", "photo-scene", "vector") or "photo" in hay):
            out.append(a)
        elif role in ("accent", "footer", "pattern", "text_headline", "text_body", "cta"):
            out.append(a)
    return out[:12]


def fill_recipe(brand_id: str, brief: Brief, recipe: Recipe, grammar: Grammar, variant_tone: str) -> Brief:
    assets = store.load_catalog(brand_id)
    pool: dict[str, list[dict]] = {}
    for slot in recipe.slots:
        cands = candidates_for_role(slot.role, assets, grammar)
        pool[slot.role] = [
            {
                "id": a.id,
                "name": a.name,
                "semantic": a.semantic,
                "tags": a.tags[:6],
                "usage": a.usage[:120],
                "exact_required": a.exact_required,
            }
            for a in cands
        ]

    payload = {
        "use_case": brief.use_case,
        "tone": variant_tone,
        "copy": brief.copy.model_dump(),
        "recipe": recipe.model_dump(),
        "ratio": brief.ratio,
        "palette": grammar.palette,
        "context_rules": [r.model_dump() for r in grammar.context_rules],
        "logo_rules": grammar.logo_rules,
        "safe_zones": grammar.safe_zones,
        "techniques": [t.model_dump() for t in grammar.techniques],
        "donts": grammar.donts[:12],
        "asset_pool": pool,
    }
    raw = llm.chat_text(FILL_SYSTEM, json.dumps(payload, ensure_ascii=False), model="pro", json_mode=True)
    data = _parse(raw)

    valid_ids = {a.id for a in assets}
    fills = []
    for f in data.get("fills", []):
        if f.get("asset_id") in valid_ids:
            fills.append(SlotFill.model_validate(f))
    brief.slots = fills
    brief.zones = [Zone.model_validate(z) for z in data.get("zones", []) if isinstance(z, dict)]
    brief.boldness = data.get("boldness", recipe.boldness)
    brief.violations = data.get("violations", [])
    brief.recipe_id = recipe.id
    brief.archetype = recipe.name

    logo_ok = any(f.role == "logo" for f in fills) or not any(s.role == "logo" for s in recipe.slots)
    if not logo_ok:
        brief.violations.append("no logo asset selected but recipe requires it")
    return brief


def validate_affinity(brand_id: str, brief: Brief, grammar: Grammar) -> list[str]:
    problems = list(brief.violations)
    filled = {f.role for f in brief.slots}
    for role in ("logo", "bg"):
        if role in filled:
            continue
        cands = candidates_for_role(role, store.load_catalog(brand_id), grammar)
        if not cands:
            if role == "logo":
                problems.append("no logo asset available in catalog")
            continue
        pick = cands[0]
        brief.slots.append(SlotFill(role=role, asset_id=pick.id, why="auto-backfilled required slot", placement="per brand rules"))
        problems.append(f"backfilled required slot '{role}' with {pick.name}")

    if brief.boldness == "simple" and len(brief.slots) > 6:
        problems.append("simple boldness should use fewer than 7 elements")
    if brief.boldness == "bold" and len(brief.slots) < 3:
        problems.append("boldness bold needs more visual elements")
    text_zones = [z for z in brief.zones if z.role.startswith("text") or z.role in ("headline", "body", "cta")]
    for z in text_zones:
        if any(v < 0 or v > 1 for v in z.rect):
            problems.append(f"zone {z.role} rect out of bounds")
    brief.violations = problems
    return problems
