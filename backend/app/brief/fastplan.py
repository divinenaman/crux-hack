"""Design planning — decides what a composition wants and how to get it.

Two planners, same contract (`list[Cohort]` with the layout-first spec:
placements + bg colour fields + bg story each):

- `plan_cohorts_llm`  — the design stage: an LLM invents distinct concepts as a
  LAYOUT of placed elements (text/logo/shape/brand assets) on a blank canvas +
  the colour-control contract for the background fill. Retrieval fetches any
  missing wants. Falls back to…
- `plan_cohorts_fast` — deterministic local fill from grammar recipes, composed
  through rotating archetype skeletons (never one template).

The old long-thinking planner stays behind DEEP_PLAN=1 (archived semantics).
"""
import json
import random
import re

from .. import config, llm, store
from ..models import Cohort, CopyBlock, Grammar, Placement, SlotFill
from .placements import (
    coordinate,
    element_zones,
    fallback_placements,
    place_element_rects,
    sanitize_fields,
    sanitize_placements,
)
from .shortlist import candidates_for_role

ANGLES = [
    "witty_pain_point",
    "aspirational_gain",
    "social_proof",
    "playful_metaphor",
    "bold_contrast",
    "warm_reassurance",
]

# Composition archetypes — the skeleton a design is composed on. Rotated per
# concept so every variant is a DIFFERENT design idea, not one template with
# new words. (name, directive)
COMPOSITIONS = [
    (
        "diagonal_tension",
        "DIAGONAL TENSION — one big mass bleeding toward a corner (hero element or headline), a small distant counterweight opposite; everything rides a single diagonal; the middle band stays open.",
    ),
    (
        "editorial_rag",
        "EDITORIAL RAG — magazine stagger: blocks alternate left and right with wildly different widths and sizes; ragged edges; one narrow type column; a tall element as a vertical spine along one edge.",
    ),
    (
        "poster_center",
        "POSTER CENTER — one giant centred statement (headline huge and tight) IS the show; everything else tiny satellites tucked asymmetrically near the edges; one element huge at a side or tiny as a stamp; an ocean of calm around the statement.",
    ),
    (
        "collage_scatter",
        "COLLAGE SCATTER — a playful cluster of 2-3 elements tilted and overlapping in one thirds-zone; headline mid-size breaking INTO the cluster's edge; tiny type counterweight far opposite; one big void.",
    ),
    (
        "split_world",
        "SPLIT WORLD — hard split of the canvas (vertical, horizontal or diagonal band) in UNEQUAL halves (35/65 or 40/60, NEVER 50/50); type lives on one side, element mass on the other; exactly ONE piece deliberately crosses the seam.",
    ),
    (
        "negative_space_hero",
        "NEGATIVE-SPACE HERO — extreme minimalism: one huge piece in a quarter of the canvas, everything else tiny and far away; at least half the canvas is untouched calm; luxury spacing.",
    ),
]

# nearest deterministic skeleton per archetype (fallback + fast path)
_SKELETON_FOR = {
    "diagonal_tension": "diagonal_tension",
    "editorial_rag": "diagonal_tension",
    "collage_scatter": "diagonal_tension",
    "poster_center": "poster_center",
    "negative_space_hero": "poster_center",
    "split_world": "split_world",
}

_SUB = {
    "witty_pain_point": "The admin pile loses. Every time.",
    "aspirational_gain": "Grow without the busywork.",
    "social_proof": "Loved by millions of small businesses.",
    "playful_metaphor": "Give your books a day off.",
    "bold_contrast": "Before the chaos. After the calm.",
    "warm_reassurance": "We've got your back.",
}
_CTA = {
    "witty_pain_point": "Fix it free",
    "aspirational_gain": "Start free",
    "social_proof": "Join them",
    "playful_metaphor": "Try it free",
    "bold_contrast": "See the difference",
    "warm_reassurance": "Get started",
}
_STORY = {
    "witty_pain_point": "name the pain, then land the punchline",
    "aspirational_gain": "show the win on the other side",
    "social_proof": "crowd energy and trust",
    "playful_metaphor": "unexpected visual metaphor",
    "bold_contrast": "stark before/after contrast",
    "warm_reassurance": "calm, human, safe hands",
}

_DEFAULT_RECIPES = [
    ("hero_photo", "photo-led hero", "lead with a photo moment", ["bg", "photo", "charm", "logo"], "balanced"),
    ("ui_moment", "product moment", "show the product in action", ["bg", "ui", "accent", "logo"], "simple"),
    ("charm_stack", "playful collage", "stack brand charms with energy", ["bg", "charm", "bloom", "accent", "logo"], "bold"),
]


def _is_element(a) -> bool:
    """Placeable elements only (logos, charms, shapes, cards) — never full
    ads/scenes. Full compositions must not be stamped into a new layout."""
    if a.cls != "element" or not a.directly_usable or a.kind in ("doc", "template", "photo-scene"):
        return False
    return True


_META_HEADLINE = re.compile(r"^\s*(create|make|generate|design|build|give\s+me|please|now|do|produce|render)\b", re.I)
_GENERIC_HEADLINES = ["Get ahead", "Made for your business", "Do more with less", "Grow with confidence"]


def _headline(use_case: str) -> str:
    core = re.split(r"[—–\-|:]", use_case, maxsplit=1)[0].strip() or use_case.strip()
    if _META_HEADLINE.search(core):
        # meta-instruction ("create 2 variations…") is NOT ad copy
        return _GENERIC_HEADLINES[len(core) % len(_GENERIC_HEADLINES)]
    words = core.replace("Get a ", "").split()
    return " ".join(words[:8]) or "Get ahead"


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        try:
            return json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return {}


def _layout(copy: CopyBlock, grammar: Grammar, catalog: list) -> tuple[list, list]:
    return fallback_placements(copy, grammar, catalog)


def _pad_slots(slots: list[SlotFill], brand_id: str, in_cohort: set[str], used: set[str], n: int) -> list[SlotFill]:
    """(archived) fixed-count padding — the layout-first spec places exactly what
    the design needs. Kept for the legacy deep planner only."""
    slots = slots[:n]
    while len(slots) < n:
        extra = [a for a in store.load_catalog(brand_id) if a.id not in in_cohort and a.id not in used and _is_element(a)]
        if not extra:
            break
        pick = extra[0]
        in_cohort.add(pick.id)
        used.add(pick.id)
        slots.append(SlotFill(role="accent", asset_id=pick.id, why="fills the fixed asset count", placement="supporting element"))
    return slots


DESIGN_SYSTEM = """You are a creative director designing on a BLANK canvas. Your design is a LAYOUT of placed pieces — text, brand elements, shapes — and a brief for the background an image model will paint in the empty space AROUND them.
Output ONLY JSON:
{"name": str, "angle": str, "story": str, "idea": str, "color_story": str,
 "archetype": str,
 "boldness": "bold"|"balanced"|"simple",
 "copy": {"headline": str, "sub": str, "body": [str], "cta": str},
 "placements": [{"kind": "text"|"image"|"shape", "role": str, "rect": [x,y,w,h], "content": str, "asset_id": str, "style": {}}],
 "bg_story": str,
 "bg_fields": [{"rect": [x,y,w,h], "intent": str, "color": "#hex", "why": str}],
 "palette_refs": [str]}

RULES:
1. placements = EVERY piece of the final canvas, positioned exactly. Rects are fractions [x,y,w,h] of the canvas. No text-text overlaps; text stays fully inside the canvas (one non-text piece may bleed past an edge — see rule 7).
   - Each image placement must use a DIFFERENT asset_id — never stamp the same asset twice in one design. If the pool runs out of distinct assets, place fewer images (a clean layout beats a repeated sticker).
   - kind "text": role headline|sub|body|cta. content = EXACT final string (FRESH ad copy marketing the brand/product; headline <= 8 words; NEVER quote the user's request). style.color = the FONT COLOUR (hex) — text has NO box/pill behind it, only font colour, so it must read on the background under it.
   - kind "image": a PLACEABLE element from the provided element_pool ONLY (use its exact "id" in asset_id). role logo|charm|ui|accent|bloom…. Prefer the colourway (see "colorway" in the pool) that will read on the background field it sits on.
   - kind "shape": deliberate geometry (pill, card, band, circle). style: {"shape":"rect"|"circle"|"pill","fill":"#hex","stroke":"#hex","strokeWidth":n,"radius":n}. A CTA pill under the CTA text is a shape — give the text a font colour that reads on the shape's fill. EVERY shape must CARRY MEANING (label plate, accent ring, colour band, photo frame) — name its role accordingly (accent_ring, cta_pill, band…); never a filler blob. Stroke-only ring: fill "none" + stroke "#hex".
2. bg_fields = the COLOUR-CONTROL contract for the background fill. Every text placement must sit in a field whose colour carries its contrast (declare "color" as a concrete hex from the brand palette when possible). intent = what the image model paints there ("deep navy field", "warm cream calm area", "soft brand-blue gradient"). why = one line (e.g. "white headline sits here").
3. bg_story = the DRAWN WORLD around your placed pieces — a full scene the image model paints in the empty space: people (a shop owner at the counter, two friends laughing over coffee), products and devices in use, rooms, streets, food, plants, objects, floating illustration accents. Be vivid and specific, like describing a picture; photographic or flat-illustration mood are both fine. The image model CAN draw people, characters and things — it must NEVER draw text, letters, numbers, words, logos or UI (it gets lettering wrong): no signs, menus, labels, banners or printed words anywhere in the scene — blank or abstract surfaces instead. All real copy stays on your placed pieces.
4. palette_refs = pick up to 4 ids from reference_pool whose colour world best fits this concept — they are the brand's palette-in-use examples.
5. Assigned angle: {angle} — commit to it. color_story must match bg_fields colours and the chosen element colourways.
6. This IS the design: say what each piece is and how it carries the story. Exact asset ids from the pools only.

COMPOSITION — assigned archetype: {comp_name}. {comp_desc}
7. COMPOSITION IS THE DESIGN. A tidy stack of same-margin blocks is a FAIL — this must SURPRISE the creator and leave them in awe:
   - SCALE DRAMA: the biggest piece (headline or lead element) spans 40–70% of ONE canvas dimension; the smallest type is 3–5× smaller than the biggest. Never uniform visual weight.
   - NO MARGIN MONOCULTURE: the three text blocks must NOT share one left edge (or one right edge) — stagger x by >=0.08 between consecutive blocks, and let at least one block use a different align (left/center/right). POSTER CENTER may deliberately centre the statement.
   - EYE PATH: place masses so the eye travels a designed route (Z, diagonal, spiral) — one big mass balanced by one small DISTANT counterweight, never symmetric halves.
   - EXACTLY ONE deliberate rule-break is MANDATORY — a design without one FAILS. Pick one:
     (a) BLEED — one shape or element cropped by the canvas edge (its rect must run past the edge, e.g. x+w > 1.0 or x < 0);
     (b) OVERLAP — an image/shape sliding under a corner of a text block, or the headline riding over an element edge (glyphs must stay fully readable on their field);
     (c) TILT — one image or shape gets style "rotation": -14..14 (degrees clockwise; never on text).
   - POOL OF CALM: one large planned empty region where the painted world breathes — designed negative space, not leftover margins.
   - LOGO WITH INTENT: a stamp, an anchor, or a scale moment — never a reflex corner tick.
8. The archetype IS your skeleton — commit to it fully. Set "archetype" to its name. Every design must read as a DIFFERENT design idea, not one template with new words."""


def _design_one(use_case: str, elements: list[dict], refs: list[dict], angle: str, brand: str, grammar: Grammar, comp: tuple[str, str]) -> dict:
    palette = grammar.palette or []
    payload = {
        "use_case": use_case,
        "brand": brand,
        "palette": palette,
        "typography": grammar.typography or {},
        "element_pool": elements,
        "reference_pool": refs,
    }
    raw = llm.chat_text(
        DESIGN_SYSTEM.replace("{angle}", angle).replace("{comp_name}", comp[0]).replace("{comp_desc}", comp[1]),
        json.dumps(payload, ensure_ascii=False),
        model="pro",
        json_mode=True,
        temperature=0.85,  # creative core — brave compositions, not tidy defaults
    )
    return _parse(raw) if raw else {}


def plan_cohorts_llm(
    brand_id: str,
    use_case: str,
    grammar: Grammar,
    n: int = 4,
    seed: int | None = None,
    folder: str = "",
) -> list[Cohort]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    catalog = [a for a in store.query_assets(brand_id, folder=folder) if a.kind != "doc"]
    if not catalog:
        return []
    # placeable pool: true elements first; thin catalogs fall back to whatever
    # is stampable (same pool as the deterministic planner) instead of bailing
    placeable = [a for a in catalog if _is_element(a)] or [a for a in catalog if a.kind != "doc"]
    elements = [
        {
            "id": a.id,
            "name": a.name,
            "kind": a.kind,
            "semantic": a.semantic,
            "tags": a.tags[:5],
            "colors": a.colors[:3],
            "colorway": a.colorway,
            "colorway_group": a.colorway_group,
        }
        for a in sorted(placeable, key=lambda a: (a.kind != "logo", a.id))[:28]
    ]
    ref_ids = set(grammar.palette_refs or [])
    refs = [
        {"id": a.id, "name": a.name, "semantic": a.semantic, "colors": a.colors[:4]}
        for a in catalog
        if a.cls == "reference" and (a.id in ref_ids or not ref_ids)
    ][:8]
    if not elements:
        return []
    angles = ANGLES[:]
    comps = COMPOSITIONS[:]
    rng = random.Random(seed)
    rng.shuffle(angles)
    rng.shuffle(comps)
    chosen = [angles[i % len(angles)] for i in range(n)]
    chosen_comp = [comps[i % len(comps)] for i in range(n)]

    # one compact design call per concept — run them concurrently
    ideas: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        futs = {
            ex.submit(_design_one, use_case, elements, refs, chosen[i], grammar.brand, grammar, chosen_comp[i]): i
            for i in range(n)
        }
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                ideas[i] = fut.result()
            except Exception:
                ideas[i] = {}

    used: set[str] = set()
    out: list[Cohort] = []
    for i in range(n):
        c = ideas.get(i) or {}
        try:
            copy = CopyBlock.model_validate(c.get("copy") or {})
            if not copy.headline:
                raise ValueError("no headline")
        except Exception:
            copy = CopyBlock(headline=_headline(use_case), sub=_SUB["warm_reassurance"], body=["Set up in minutes."], cta="Get started")

        placements = sanitize_placements(c.get("placements") or [], copy, catalog)
        fields = sanitize_fields(c.get("bg_fields") or [])
        if not any(p.kind == "text" and p.role.replace("text_", "") == "headline" for p in placements):
            placements, fields = fallback_placements(copy, grammar, catalog, _SKELETON_FOR.get(chosen_comp[i][0], "diagonal_tension"))
        placements, coord_notes = coordinate(placements, fields, catalog, grammar)

        # honour per-concept colourway picks + de-dupe placed assets across concepts
        slots = [
            SlotFill(role=p.role, asset_id=p.asset_id, why=str(p.style.get("fit") or "placed"), placement=f"{p.kind} at {[round(v,2) for v in p.rect]}")
            for p in placements
            if p.kind == "image" and p.asset_id
        ]
        palette_refs = [r for r in (c.get("palette_refs") or []) if isinstance(r, str) and r in ref_ids] or grammar.palette_refs or []
        bg_story = str(c.get("bg_story") or f"{c.get('idea') or ''} — atmospheric background only, no text or logos.")
        idea = str(c.get("idea") or "")
        if chosen_comp[i][0]:
            idea = f"{chosen_comp[i][0]} — {idea}" if idea else chosen_comp[i][0]
        out.append(
            Cohort(
                id=f"idea_{i+1}",
                name=str(c.get("name") or f"design {i+1}"),
                angle=str(c.get("angle") or chosen[i]),
                story=str(c.get("story") or ""),
                idea=idea,
                color_story=str(c.get("color_story") or ""),
                recipe_id="",
                boldness=c.get("boldness") if c.get("boldness") in ("bold", "balanced", "simple") else "balanced",
                copy=copy,
                slots=slots,
                placements=placements,
                bg_fields=fields,
                bg_story=bg_story,
                palette_refs=palette_refs,
            )
        )
        if coord_notes:
            out[-1].idea = (out[-1].idea + " · " if out[-1].idea else "") + "colour-coordinated"
    return out


def plan_cohorts_fast(
    brand_id: str,
    use_case: str,
    grammar: Grammar,
    n: int = 4,
    seed: int | None = None,
    folder: str = "",
) -> list[Cohort]:
    rng = random.Random(seed)
    catalog = store.query_assets(brand_id, folder=folder)
    assets = [a for a in catalog if _is_element(a)] or [a for a in catalog if a.kind != "doc"]
    if not assets:
        return []

    recipes = grammar.recipes or []
    if not recipes:
        from ..models import Recipe, RecipeSlot

        recipes = [
            Recipe(id=i, name=nm, intent=intent, slots=[RecipeSlot(role=r, description=r) for r in roles], boldness=b)
            for i, nm, intent, roles, b in _DEFAULT_RECIPES
        ]

    angles = ANGLES[:]
    rng.shuffle(angles)
    comps = ["diagonal_tension", "poster_center", "split_world"]
    rng.shuffle(comps)
    used: set[str] = set()
    out: list[Cohort] = []

    for i in range(n):
        angle = angles[i % len(angles)]
        arch = comps[i % len(comps)]
        recipe = recipes[i % len(recipes)]
        slots: list[SlotFill] = []
        in_cohort: set[str] = set()
        for s in recipe.slots:
            role = s.role
            if role.startswith("text") or role in ("headline", "sub", "body", "cta", "logo_footer"):
                continue
            cands = candidates_for_role(role, assets, grammar)
            fresh = [a for a in cands if a.id not in used and a.id not in in_cohort]
            if not fresh:
                # prefer variety across concepts — but NEVER stamp the same asset
                # twice in one cohort; reuse an asset from another cohort first,
                # and place fewer pieces when nothing unused is left
                fresh = [a for a in assets if a.id not in in_cohort]
            pool = fresh
            if not pool:
                continue
            pick = pool[(i + 1) % len(pool)]
            if "logo" not in role:
                used.add(pick.id)
            in_cohort.add(pick.id)
            slots.append(
                SlotFill(
                    role=role,
                    asset_id=pick.id,
                    why=f"{pick.semantic or pick.name} — {pick.tags[0] if pick.tags else pick.kind} fits this angle",
                    placement=f"{role} layer, per recipe '{recipe.name}'",
                )
            )

        headline = _headline(use_case)
        copy = CopyBlock(
            headline=headline,
            sub=_SUB[angle],
            body=[f"{use_case.split('—')[0].strip()[:60]} — made simple.", "Set up in minutes."],
            cta=_CTA[angle],
        )
        # deterministic layout: composed archetype skeleton, then stamp the
        # recipe's elements into overlap-free zones against the pieces placed
        placements, fields = fallback_placements(copy, grammar, catalog, arch)
        taken = [p.rect for p in placements if p.kind in ("text", "shape", "image")]
        rects = place_element_rects(len(slots), taken, zones=element_zones(arch))
        for s, rect in zip(slots, rects):
            placements.append(
                Placement(kind="image", role=s.role, rect=rect, asset_id=s.asset_id, style={"fit": "contain"})
            )
        placements, _ = coordinate(placements, fields, catalog, grammar)

        lead = next((a for a in assets if any(s.asset_id == a.id for s in slots)), assets[0])
        color_story = ", ".join((lead.colors or ["brand navy"])[:2]) + f" — {_STORY[angle]}"
        out.append(
            Cohort(
                id=f"idea_{i + 1}",
                name=f"{recipe.name} · {angle.replace('_', ' ')} · {arch.replace('_', ' ')}",
                angle=angle,
                story=_STORY[angle],
                idea=f"{headline}: {_STORY[angle]} ({recipe.intent}) — composed as {arch.replace('_', ' ')}",
                color_story=color_story,
                recipe_id=recipe.id,
                boldness=recipe.boldness,
                copy=copy,
                slots=slots,
                placements=placements,
                bg_fields=fields,
                bg_story=f"{_STORY[angle]} — {recipe.intent}: a full scene with people, products and illustration elements around the pieces; smooth brand-colour fields under the copy; no text, no logos.",
                palette_refs=grammar.palette_refs or [],
            )
        )
    return out
