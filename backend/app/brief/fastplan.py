"""Design planning — decides what a composition wants and how to get it.

Two planners, same contract (`list[Cohort]`, EXACTLY config.ASSETS_PER_COMPOSITION
slots per cohort):

- `plan_cohorts_llm`  — the design stage: an LLM invents distinct concepts and
  states what assets it WANTS (searchable descriptions) + placement; retrieval
  (app.rag) then FETCHES each want from the catalog. Falls back to…
- `plan_cohorts_fast` — deterministic local fill from grammar recipes.

The old long-thinking planner stays behind DEEP_PLAN=1.
"""
import json
import random
import re

from .. import config, llm, store
from ..models import Cohort, CopyBlock, Grammar, SlotFill, Zone
from ..rag import retrieve
from .shortlist import candidates_for_role

ANGLES = [
    "witty_pain_point",
    "aspirational_gain",
    "social_proof",
    "playful_metaphor",
    "bold_contrast",
    "warm_reassurance",
]

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
    """Harvestable elements (charms, logos, cards, crops) — never full ads/scenes.
    Full ad compositions must not be stamped into a new composition as accents."""
    if not a.directly_usable or a.kind in ("doc", "template"):
        return False
    if "__e" in a.id or a.kind in ("charm", "bloom", "logo", "single", "illustration", "grid-cell"):
        return True
    return (a.usage or "").lower().startswith("extracted")


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


def _layout(copy: CopyBlock) -> list[Zone]:
    return [
        Zone(role="bg", rect=[0, 0, 1, 1], text_free=True, content=""),
        Zone(role="headline", rect=[0.06, 0.06, 0.88, 0.16], content=copy.headline),
        Zone(role="sub", rect=[0.06, 0.24, 0.7, 0.08], content=copy.sub),
        Zone(role="body", rect=[0.06, 0.36, 0.55, 0.2], text_free=True, content=" ".join(copy.body)),
        Zone(role="cta", rect=[0.06, 0.8, 0.3, 0.09], text_free=True, content=copy.cta),
        Zone(role="logo_footer", rect=[0.78, 0.8, 0.16, 0.12], content=""),
    ]


def _pad_slots(slots: list[SlotFill], brand_id: str, in_cohort: set[str], used: set[str], n: int) -> list[SlotFill]:
    """Enforce the fixed asset count: truncate to n, pad with unused ELEMENT assets.
    Never pad with full ads/scenes — fewer real elements beats junk stamps."""
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


DESIGN_SYSTEM = """You are a creative director. Design ONE distinct ad concept for the use case.
Output ONLY JSON:
{"name": str, "angle": str, "story": str, "idea": str, "color_story": str,
 "boldness": "bold"|"balanced"|"simple",
 "copy": {"headline": str, "sub": str, "body": [str], "cta": str},
 "asset_wants": [{"role": str, "want": str, "placement": str}],
 "zones": [{"role": str, "rect": [x,y,w,h], "content": str, "text_free": bool}]}

RULES:
1. asset_wants = EXACTLY {per} entries. "want" = what the composition should SHOW — a searchable description of a brand asset ("beekeeper illustration", "navy brushstroke logo", "coins and sparkles"). "placement" = exactly where it goes and what it does. "role" = one of bg|photo|charm|bloom|logo|ui|accent.
2. This IS the design: state what you want and how each piece carries the story. Prefer wants that exist in the provided asset_pool (search its name/semantic/tags) — retrieval fetches the closest match.
3. copy: exact final strings — FRESH ad copy marketing the brand/product. headline <= 8 words. NO placeholders. NEVER quote or paraphrase the user's request/instruction as copy.
4. Assigned angle: {angle} — commit to it.
5. zones = the SUPER DETAILED WIREFRAME of the final canvas: EVERY piece (bg/photo, each charm/ui/logo element, headline, sub, body, cta) with its exact rect as fractions [x,y,w,h] of the canvas and its exact content string. No overlaps of text zones; stay inside the canvas. The image model will realize exactly this wireframe — it must be complete and precise."""


def _design_one(use_case: str, digest: list[dict], angle: str, brand: str) -> dict:
    N = max(1, config.ASSETS_PER_COMPOSITION)
    payload = {
        "use_case": use_case,
        "assets_per_composition": N,
        "brand": brand,
        "asset_pool": digest,
    }
    raw = llm.chat_text(
        DESIGN_SYSTEM.replace("{per}", str(N)).replace("{angle}", angle),
        json.dumps(payload, ensure_ascii=False),
        model="pro",
        json_mode=True,
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

    N = max(1, config.ASSETS_PER_COMPOSITION)
    catalog = [a for a in store.query_assets(brand_id, folder=folder) if a.kind != "doc"]
    if not catalog:
        return []
    digest = [
        {"id": a.id, "name": a.name, "kind": a.kind, "semantic": a.semantic, "tags": a.tags[:5], "colors": a.colors[:3]}
        for a in (sorted(catalog, key=lambda a: (not a.directly_usable, a.id)))[:24]
    ]
    angles = ANGLES[:]
    random.Random(seed).shuffle(angles)
    chosen = [angles[i % len(angles)] for i in range(n)]

    # one compact design call per concept — run them concurrently
    ideas: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        futs = {ex.submit(_design_one, use_case, digest, chosen[i], grammar.brand): i for i in range(n)}
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
        wants = [w for w in c.get("asset_wants", []) if isinstance(w, dict)][:N]
        slots: list[SlotFill] = []
        in_cohort: set[str] = set()
        for w in wants:
            role = str(w.get("role") or "accent")
            want = str(w.get("want") or role)
            hits = retrieve(brand_id, want, k=4, exclude=used | in_cohort)
            if not hits:
                hits = retrieve(brand_id, role, k=4, exclude=used | in_cohort)
            if role in ("accent", "charm", "bloom"):
                el = [a for a in hits if _is_element(a)]
                hits = el or []
            if not hits:
                hits = [a for a in catalog if a.id not in in_cohort and _is_element(a)][:1]
            if not hits:
                continue
            pick = hits[0]
            in_cohort.add(pick.id)
            if "logo" not in role:
                used.add(pick.id)
            slots.append(SlotFill(role=role, asset_id=pick.id, why=want, placement=str(w.get("placement") or "per design plan")))
        slots = _pad_slots(slots, brand_id, in_cohort, used, N)
        if not slots:
            continue
        try:
            copy = CopyBlock.model_validate(c.get("copy") or {})
            if not copy.headline:
                raise ValueError("no headline")
        except Exception:
            copy = CopyBlock(headline=_headline(use_case), sub=_SUB["warm_reassurance"], body=["Set up in minutes."], cta="Get started")
        zones = _wireframe_zones(c.get("zones"), copy)
        out.append(
            Cohort(
                id=f"idea_{i+1}",
                name=str(c.get("name") or f"design {i+1}"),
                angle=str(c.get("angle") or chosen[i]),
                story=str(c.get("story") or ""),
                idea=str(c.get("idea") or ""),
                color_story=str(c.get("color_story") or ""),
                recipe_id="",
                boldness=c.get("boldness") if c.get("boldness") in ("bold", "balanced", "simple") else "balanced",
                copy=copy,
                slots=slots,
                zones=zones,
            )
        )
    return out


def _wireframe_zones(raw_zones, copy: CopyBlock) -> list[Zone]:
    """Validated LLM wireframe zones; fall back to the coarse template."""
    out: list[Zone] = []
    for z in raw_zones or []:
        if not isinstance(z, dict):
            continue
        try:
            r = [float(v) for v in z.get("rect") or []]
            if len(r) != 4 or any(v < -0.05 or v > 1.05 for v in r):
                continue
            r = [max(0.0, min(1.0, v)) for v in r]
            if r[2] <= 0.01 or r[3] <= 0.01:
                continue
            out.append(
                Zone(
                    role=str(z.get("role") or "accent"),
                    rect=r,
                    content=str(z.get("content") or ""),
                    text_free=bool(z.get("text_free")),
                )
            )
        except (TypeError, ValueError):
            continue
    if not any(z.role in ("headline", "text_headline") for z in out):
        return _layout(copy)
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
    assets = [a for a in catalog if a.directly_usable and a.kind != "doc"] or [a for a in catalog if a.kind != "doc"]
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
    used: set[str] = set()
    out: list[Cohort] = []

    for i in range(n):
        angle = angles[i % len(angles)]
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
                # widen to any unused asset before ever repeating one in a cohort
                fresh = [a for a in assets if a.id not in used and a.id not in in_cohort]
            pool = fresh or cands
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
        if not slots:
            continue
        slots = _pad_slots(slots, brand_id, in_cohort, used, max(1, config.ASSETS_PER_COMPOSITION))

        headline = _headline(use_case)
        copy = CopyBlock(
            headline=headline,
            sub=_SUB[angle],
            body=[f"{use_case.split('—')[0].strip()[:60]} — made simple.", "Set up in minutes."],
            cta=_CTA[angle],
        )
        lead = next((a for a in assets if any(s.asset_id == a.id for s in slots)), assets[0])
        color_story = ", ".join((lead.colors or ["brand navy"])[:2]) + f" — {_STORY[angle]}"
        out.append(
            Cohort(
                id=f"idea_{i + 1}",
                name=f"{recipe.name} · {angle.replace('_', ' ')}",
                angle=angle,
                story=_STORY[angle],
                idea=f"{headline}: {_STORY[angle]} ({recipe.intent})",
                color_story=color_story,
                recipe_id=recipe.id,
                boldness=recipe.boldness,
                copy=copy,
                slots=slots,
                zones=_layout(copy),
            )
        )
    return out
