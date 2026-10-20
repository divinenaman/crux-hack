import json
import re

from .. import llm
from ..models import Brief, CriticItem, CriticReport, Grammar

CRITIC_SYSTEM = """You are a strict brand-design judge. Score the candidate ad against the brief and its WIREFRAME (the zones list = the exact expected layout).
Output ONLY JSON:
{"score": 0..100,
 "items": [{"check": str, "pass": bool, "note": str, "fix_prompt": str}],
 "fixes": [str]}

Checks (all required):
1. copy_fidelity — every headline/sub/body/cta string rendered exactly (no typos, no invented text).
2. text_free_clean — text-free zones contain no scribbled/garbled text.
3. wireframe_fidelity — every wireframe zone is realized at its specified rect (fractions) with its content; no zone missing, no piece outside its zone.
4. asset_fidelity — reference elements appear close to exact (not redrawn, right element per role).
5. brand_rules — palette only, logo colourway matches bg (use the EXACT logo variant named in the brief, e.g. "Xero Logo White"), safe zones respected.
6. technique — composition uses the required techniques (crop/layer/break-frame etc).
7. artifacts — no visual artifacts, mushy edges, extra limbs/text/watermarks.
8. composition — strong hierarchy, balanced, professional finish.

NOTE: baked text and the footer logo are erased later and re-composited as exact live layers.
- copy strings must STILL be rendered exactly (the erasure matches them character-by-character).
- The logo must still be the correct variant/colourway and roughly reference-accurate, but do NOT fail asset_fidelity/artifacts merely for redraw softness on the logo; fail it for missing/misplaced/wrong-variant logo or for non-logo reference elements that were redrawn.

FIX PROMPT LANGUAGE (critical):
- NEVER write generic instructions like "remove text" or "fix the logo" or "improve layout".
- ALWAYS quote the exact string or name the exact element + its exact location using region + fractions.
  GOOD: 'Remove the exact text string "Numbers don\\'t bite." in the headline zone starting at left=10%, top=15%, sized 80% wide × 25% tall, and inpaint the white card behind it'
  BAD: 'remove the headline text'
  GOOD: 'Replace the lowercase grey word "xeo" in the footer logo zone starting at left=10%, top=90% with the exact Xero wordmark from reference asset 2'
  BAD: 'fix the logo'
- One fix per failing item. fix_prompt must be actionable alone.
score = 100 * (passes/8), adjusted -5..-20 for severity."""

STRIP_VERIFY_SYSTEM = """You verify that an edited ad image has NO readable leftovers of the listed strings and no listed logo.
Output ONLY JSON: {"clean": bool, "leftovers": [{"content_guess": str, "where": str, "fix_prompt": str}]}
Report ONLY leftovers of the listed items — other text that is not listed is expected to remain and must NOT be flagged.
fix_prompt must quote the exact leftover string and its location (region + approximate fractions). No generic wording."""


def judge(image_path: str, brief: Brief, grammar: Grammar, brand_id: str = "") -> CriticReport:
    payload = {
        "use_case": brief.use_case,
        "story": brief.story,
        "idea": brief.idea,
        "color_story": brief.color_story,
        "copy": brief.copy.model_dump(),
        "zones": [z.model_dump() for z in brief.zones],
        "slots": [s.model_dump() for s in brief.slots],
        "boldness": brief.boldness,
        "palette": grammar.palette,
        "logo_rules": grammar.logo_rules,
        "techniques": [t.model_dump() for t in grammar.techniques[:8]],
        "donts": [d for d in grammar.donts if not d.startswith("doc_page")][:10],
    }
    parts = [
        {"type": "text", "text": CRITIC_SYSTEM},
        {"type": "text", "text": "BRIEF:\n" + json.dumps(payload, ensure_ascii=False)},
        {"type": "text", "text": "CANDIDATE AD:"},
        llm.img_part(image_path, detail="high"),
    ]
    raw = llm.chat_vision("", parts, model="pro", json_mode=True)
    data = _parse(raw)
    items = []
    for it in data.get("items", []):
        it.setdefault("pass", False)
        it["fix_prompt"] = _harden_fix(it.get("fix_prompt", ""), it.get("note", ""), brief)
        items.append(CriticItem.model_validate(it))
    fixes = [f for f in data.get("fixes", []) if isinstance(f, str) and f.strip()]
    for it in items:
        if not it.pass_ and it.fix_prompt and it.fix_prompt not in fixes:
            fixes.append(it.fix_prompt)
    report = CriticReport(score=float(data.get("score", 0)), items=items, fixes=fixes[:3])
    verify = verify_fidelity(image_path, brief, brand_id)
    report.items += verify
    fails = [i for i in report.items if not i.pass_]
    report.score = round(100.0 * (len(report.items) - len(fails)) / max(1, len(report.items)), 1)
    report.fixes = ([i.fix_prompt for i in fails if i.fix_prompt][:2] + report.fixes)[:3]
    return report


def verify_strip(image_path: str, brief: Brief) -> tuple[bool, list[str]]:
    strings = []
    for z in brief.zones:
        if z.style.get("replace") is False:
            continue  # kept baked — it is allowed to remain
        c = z.content
        if z.role in ("headline", "text_headline"):
            c = brief.copy.headline
        elif z.role in ("sub", "text_sub", "subhead"):
            c = brief.copy.sub
        elif z.role in ("body", "text_body"):
            c = " / ".join(brief.copy.body)
        elif z.role == "cta":
            c = brief.copy.cta
        if c and z.role not in ("logo", "logo_footer", "footer"):
            strings.append(c)
    parts = [
        {"type": "text", "text": STRIP_VERIFY_SYSTEM},
        {"type": "text", "text": f"Strings that must be GONE: {json.dumps(strings, ensure_ascii=False)}"},
        {"type": "text", "text": "IMAGE:"},
        llm.img_part(image_path, detail="high"),
    ]
    raw = llm.chat_vision("", parts, model="flash", json_mode=True)
    data = _parse(raw)
    fixes = []
    for l in data.get("leftovers", []) or []:
        fp = l.get("fix_prompt") or ""
        if not fp:
            guess = l.get("content_guess", "")
            where = l.get("where", "")
            fp = f'Remove the exact leftover text string "{guess}" at {where} and inpaint the background behind it'
        fixes.append(fp)
    return bool(data.get("clean")), fixes


def _harden_fix(fix: str, note: str, brief: Brief) -> str:
    if not fix:
        return ""
    generic = any(k in fix.lower() for k in ("remove text", "fix the logo", "improve layout", "fix text", "remove the text", "fix the text"))
    has_quote = '"' in fix or "'" in fix
    if not generic and (has_quote or any(r in fix for r in ("headline zone", "cta", "footer", "left="))):
        return fix
    m = re.search(r'"([^"]{2,})"', note or "")
    exact = m.group(1) if m else (brief.copy.headline if "headline" in (fix + note).lower() else "")
    where = "its zone (see brief zones for exact fractions)"
    if exact:
        return f'Remove the exact text string "{exact}" at {where} and inpaint the background behind it'
    return fix + " — specify the exact element and its zone fractions"


def verify_fidelity(image_path: str, brief: Brief, brand_id: str = "") -> list[CriticItem]:
    from .match import find_assets

    items = []
    found = find_assets(brand_id, image_path, [f.asset_id for f in brief.slots]) if brand_id else {}
    for fill in brief.slots:
        is_logo = fill.role in ("logo", "logo_footer", "footer") or "logo" in fill.role
        if is_logo:
            # logo is erased by the strip step and re-placed as an exact live layer
            # (paste_exact + zone fallback) — NCC on the transient bake is a false penalty.
            items.append(
                CriticItem(
                    check=f"asset_match:{fill.asset_id}",
                    **{"pass": True},
                    note="logo re-placed as exact live layer after strip",
                    fix_prompt="",
                )
            )
            continue
        hit = found.get(fill.asset_id)
        ok = bool(hit and hit.get("score", 0) > 0.4)
        items.append(
            CriticItem(
                check=f"asset_match:{fill.asset_id}",
                **{"pass": ok},
                note=f"template score {hit.get('score') if hit else 'n/a'}",
                fix_prompt=""
                if ok
                else f'Replace the {fill.role} element at {fill.placement or "its planned position"} with the exact reference asset "{fill.asset_id}" from the contact sheet — same curves and colours as the reference, not a redraw',
            )
        )
    return items


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}
