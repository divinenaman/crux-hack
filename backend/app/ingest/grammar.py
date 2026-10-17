import json
import re
from pathlib import Path

from .. import llm
from ..models import (
    ContextRule,
    Grammar,
    LexiconEntry,
    Recipe,
    RecipeSlot,
    Technique,
)

GRAMMAR_SYSTEM = """You are a brand-ops parser. You read brand-book pages and output a machine grammar JSON.
Output ONLY JSON with this schema:
{
 "brand": str,
 "palette": [{"name": str, "hex": str, "usage": str}],
 "lexicon": [{"id": str, "name": str, "family": str, "semantic": str, "colors": [str]}],
 "techniques": [{"name": str, "applies_to": str, "instruction": str}],
 "context_rules": [{"name": str, "when": str, "then": str}],
 "recipes": [{"id": str, "name": str, "intent": str, "boldness": "bold"|"balanced"|"simple",
              "slots": [{"role": str, "description": str, "optional": bool}], "example_refs": [str]}],
 "logo_rules": {"colorways": [{"bg": str, "logo": str, "contrast": str, "hex": str}], "donts": [str], "placement": [str]},
 "safe_zones": {"placements": [{"name": str, "rules": [str]}]},
 "typography": {"headline_font": str, "body_font": str, "notes": str},
 "donts": [str]
}
Rules:
- lexicon = every named shape/icon family you see (e.g. named blooms, charm motifs), with semantic meaning words.
- techniques = actionable usage rules (crop, layer, break-frame, patterning limits, photo masking).
- context_rules = conditional selection rules (funnel stage -> boldness, aspect ratio -> template family, background -> logo colourway).
- recipes = composition recipes with role slots that group assets together. Slot roles: bg, mask, bloom, charm, logo, ui, text_headline, text_body, cta, footer.
- Merge pages into ONE grammar. Be literal to the page text. No invention."""

DOC_KINDS = ("doc", "guidelines", "lexicon", "grammar")


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def extract_grammar_pages(page_paths: list[str], existing: Grammar | None = None) -> Grammar:
    parts = [{"type": "text", "text": f"Brand-book pages ({len(page_paths)}). Merge into one grammar JSON."}]
    for p in page_paths:
        parts.append({"type": "text", "text": f"PAGE: {Path(p).name}"})
        parts.append(llm.img_part(p))
    raw = llm.chat_vision(GRAMMAR_SYSTEM, parts, model="pro", json_mode=True)
    data = _parse_json(raw)

    g = Grammar(
        brand=data.get("brand", ""),
        palette=data.get("palette", []),
        lexicon=[LexiconEntry.model_validate(x) for x in data.get("lexicon", [])],
        techniques=[Technique.model_validate(x) for x in data.get("techniques", [])],
        context_rules=[ContextRule.model_validate(x) for x in data.get("context_rules", [])],
        logo_rules=data.get("logo_rules", {}),
        safe_zones=data.get("safe_zones", {}),
        typography=data.get("typography", {}),
        donts=data.get("donts", []),
    )
    for r in data.get("recipes", []):
        r.setdefault("id", re.sub(r"\W+", "_", r.get("name", "recipe")).lower())
        r.setdefault("slots", [])
        r["slots"] = [RecipeSlot.model_validate(s) for s in r["slots"]]
        g.recipes.append(Recipe.model_validate(r))

    if existing:
        seen = {(e.family, e.name) for e in g.lexicon}
        for e in existing.lexicon:
            if (e.family, e.name) not in seen:
                g.lexicon.append(e)
        names = {t.name for t in g.techniques}
        g.techniques += [t for t in existing.techniques if t.name not in names]
        ids = {r.id for r in g.recipes}
        g.recipes += [r for r in existing.recipes if r.id not in ids]
        if not g.palette:
            g.palette = existing.palette
        if not g.logo_rules:
            g.logo_rules = existing.logo_rules
    return g
