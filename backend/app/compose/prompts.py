import json

from .. import config, store
from ..models import Brief, Grammar

RATIO_SIZE = {"1:1": "1024x1024", "4:5": "1024x1536", "9:16": "1024x1536", "16:9": "1536x1024"}

_REGION = {
    "headline": "the headline zone",
    "text_headline": "the headline zone",
    "sub": "the subhead zone",
    "text_sub": "the subhead zone",
    "subhead": "the subhead zone",
    "body": "the body copy zone",
    "text_body": "the body copy zone",
    "cta": "the CTA button",
    "logo": "the footer logo",
    "logo_footer": "the footer logo",
    "footer": "the footer",
}


def size_for(ratio: str) -> str:
    return RATIO_SIZE.get(ratio, "1024x1024")


def rect_phrase(rect: list[float]) -> str:
    x, y, w, h = rect
    return f"starting at left={x:.0%}, top={y:.0%}, sized {w:.0%} wide × {h:.0%} tall"


def region_name(role: str) -> str:
    return _REGION.get(role, f"the {role} zone")


def text_of(brief: Brief, role: str) -> str:
    if role in ("headline", "text_headline"):
        return brief.copy.headline
    if role in ("sub", "text_sub", "subhead"):
        return brief.copy.sub
    if role in ("body", "text_body"):
        return "\n".join(brief.copy.body)
    if role == "cta":
        return brief.copy.cta
    return ""


def _asset_lines(brief: Brief, brand_id: str = "") -> list[str]:
    lines = []
    for i, fill in enumerate(brief.slots[: config.MAX_ASSET_REFS]):
        a = store.get_asset(brand_id, fill.asset_id) if brand_id else None
        if not a:
            continue
        why = fill.why or a.usage
        lines.append(
            f"{i + 1}. [{fill.role}] \"{a.name}\" — meaning: {a.semantic or ', '.join(a.tags[:3])}. "
            f"WHY in this story: {why} PLACEMENT: {fill.placement or a.usage}"
        )
    return lines


def _zone_lines(brief: Brief) -> list[str]:
    out = []
    for z in brief.zones:
        content = text_of(brief, z.role) or z.content
        if z.role == "cta":
            action = f'render a pill CTA button labelled exactly "{content}"'
        elif z.role in ("logo", "logo_footer", "footer"):
            variant = f' — variant "{content}"' if content else ""
            action = (
                "place the brand wordmark logo exactly as the reference logo asset"
                f"{variant} (same letterforms and colour as the reference — do not redraw the wordmark text, "
                "do not recolour it, do not restyle it)"
            )
        else:
            action = f'render the text exactly as: "{content}"'
        out.append(f"- {region_name(z.role)} at {rect_phrase(z.rect)}: {action}.")
    return out


def build_prompt(brief: Brief, grammar: Grammar, ref_note: str = "", brand_id: str = "") -> str:
    tech = "\n".join(f"- {t.name}: {t.instruction}" for t in grammar.techniques[:8])
    donts = "\n".join(f"- {d}" for d in grammar.donts[:10] if not d.startswith("doc_page"))
    rules = "\n".join(f"- {c.name}: when {c.when} then {c.then}" for c in grammar.context_rules[:8])
    palette = ", ".join(f"{p.get('name','')} {p.get('hex','')}" for p in grammar.palette[:8])
    logo = json.dumps(grammar.logo_rules.get("colorways", [])[:4], ensure_ascii=False)

    return f"""Design ONE polished brand advertisement. You are realizing a SPECIFIC creative idea (follow it, do not invent a new one).
Brand assets (logos, charms, blooms) must be copied pixel-perfectly from the references — never redrawn text, never recoloured.

CREATIVE IDEA
- Story: {brief.story}
- Concept: {brief.idea}
- Angle: {brief.archetype} ({brief.recipe_id})
- Colour story: {brief.color_story}
- Boldness: {brief.boldness}. Aspect: {brief.ratio}. Brand: {grammar.brand}.

PALETTE (only these colours): {palette}

COMPOSITION TECHNIQUES (apply literally):
{tech}

CONTEXT RULES:
{rules}

LOGO COLOURWAYS (pick the pair matching the background; the LAYOUT logo line names the exact variant to use — never invent another): {logo}

DO NOT:
{donts}

ASSETS {ref_note} — numbered on the contact sheet. Copy each numbered reference element PIXEL-PERFECTLY (identical letterforms, identical curves, identical colours). Never trace, simplify, flatten, restyle, or "improve" them; they are brand assets, not art to reinterpret:
{chr(10).join(_asset_lines(brief, brand_id))}

LAYOUT (fractions of the canvas — place precisely; the attached WIREFRAME image shows this exact layout and must be realized exactly):
{chr(10).join(_zone_lines(brief))}

Craft like a senior brand designer: strong hierarchy, one hero focus, generous margins, shapes cropped boldly / breaking frames per techniques.
Clear visual hierarchy: headline dominant on at most 2–3 short lines, sub/body secondary and lighter, CTA prominent; do not stack every text block in one narrow column.
Crisp flat brand artwork: clean vector edges, no drop shadows or glows on vector/charm elements, no mushy or blurred edges.
Text-free zones (body/CTA if marked) stay clean. No watermarks. No text beyond the strings above."""


def build_fix_prompt(brief: Brief, fix: str) -> str:
    return (
        f"Surgical edit. Change EXACTLY this and nothing else: {fix}. "
        f"Everything else stays pixel-identical: same layout, same colours, same shapes. "
        f"All strings stay EXACTLY: headline \"{brief.copy.headline}\", sub \"{brief.copy.sub}\", "
        f"body {brief.copy.body}, cta \"{brief.copy.cta}\"."
    )


def build_strip_prompt(brief: Brief) -> str:
    lines = []
    i = 1
    for z in brief.zones:
        if z.style.get("replace") is False:
            continue  # element stays baked — never ask for its removal
        content = text_of(brief, z.role) or z.content
        if z.role in ("logo", "logo_footer", "footer"):
            lines.append(
                f'{i}. Remove the brand wordmark logo picture that sits in {region_name(z.role)}, {rect_phrase(z.rect)}. '
                f"Erase it fully and inpaint the background behind it."
            )
        elif content:
            verb = (
                f'Remove the exact label text "{content}" that sits in {region_name(z.role)}, {rect_phrase(z.rect)}. '
                f"Keep the pill button shape itself — leave it empty and clean."
                if "cta" in z.role
                else f'Remove the exact text string "{content}" that sits in {region_name(z.role)}, {rect_phrase(z.rect)}. '
                f"Erase every letter of it fully and inpaint the card/background behind it so it looks clean and empty."
            )
            lines.append(f"{i}. {verb}")
        i += 1
    return (
        "Edit this ad image: erase ONLY the specific text/logo items listed below, then inpaint clean background/card behind them.\n"
        "Remove EXACTLY these (match the strings character-by-character):\n"
        + "\n".join(lines)
        + "\n\nAfter the edit every listed string must be GONE — but any text or mark NOT listed above must stay EXACTLY as it is.\n"
        "Keep everything else pixel-identical: same composition, same colours, same decorative shapes at the same positions.\n"
        "Do NOT invent new elements. Do NOT leave ghosting or smudges where the removed items used to be."
    )


def build_placement_tune_payload(brief: Brief) -> dict:
    zones = []
    for z in brief.zones:
        content = text_of(brief, z.role) or z.content
        zones.append(
            {
                "role": z.role,
                "region": region_name(z.role),
                "current_rect": z.rect,
                "content": content,
                "style": z.style,
            }
        )
    return {
        "zones": zones,
        "copy": brief.copy.model_dump(),
        "color_story": brief.color_story,
    }
