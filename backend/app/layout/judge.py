"""Layout judge + perfect loop — BEFORE any pixels are generated.

Det checks (code, instant): bounds · text-text overlap · piece-vs-text collision
(text on its own CTA shape is legal) · copy fits its box · WCAG contrast of each
font colour against the bg under it (field colour or shape fill) · logo clearspace.

Vision check (spatial model on the layout proof): hierarchy, balance, alignment,
brand feel.

perfect_layout() runs the loop: judge → reasoning model adjusts the placement
spec → re-render → re-judge. Cheap (no image gen) — the canvas is positioned,
judged and perfected before the fill ever runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import llm
from ..brief.placements import bg_hex_for, contrast_ratio, overlaps
from ..fidelity.typo import fit_text_block, resolve_font_path
from .canvas import DEFAULT_TEXT_COLOR
from ..models import Brief, CriticItem, CriticReport, Placement

MIN_TEXT_PX = 12.0
EDGE_MARGIN = 0.015


def _item(check: str, ok: bool, note: str, fix: str = "") -> CriticItem:
    return CriticItem(**{"check": check, "pass": ok, "note": note, "fix_prompt": fix})


def det_check(brief: Brief) -> list[CriticItem]:
    items: list[CriticItem] = []
    ps = brief.placements
    texts = [p for p in ps if p.kind == "text"]
    pieces = [p for p in ps if p.kind in ("image", "shape")]

    # 1. bounds
    oob = [p for p in ps if p.rect[0] < -0.02 or p.rect[1] < -0.02 or p.rect[0] + p.rect[2] > 1.02 or p.rect[1] + p.rect[3] > 1.02]
    items.append(_item("bounds", not oob, f"{len(oob)} pieces outside canvas" if oob else "all pieces inside canvas",
                       "Move every placement fully inside the canvas (rects are x,y,w,h fractions)."))

    # 2. text-text overlap
    tt = []
    for i, a in enumerate(texts):
        for b in texts[i + 1 :]:
            if overlaps(a.rect, b.rect, pad=0.005):
                tt.append(f"{a.role}×{b.role}")
    items.append(_item("text_separation", not tt, f"text overlaps: {tt}" if tt else "no text-text overlaps",
                       "Separate the overlapping text blocks — no two text placements may overlap."))

    # 3. piece-vs-text collision (text ON its own shape is legal — CTA pill)
    bad = []
    for t in texts:
        for p in pieces:
            if not overlaps(t.rect, p.rect, pad=0.004):
                continue
            legal = (
                p.kind == "shape"
                and _covers(p.rect, t.rect, frac=0.55)
                and ("cta" in t.role and "cta" in p.role or p.role.endswith("_pill") or (p.style or {}).get("shape") in ("pill", "rect", "circle"))
            )
            if not legal:
                bad.append(f"{t.role}×{p.role}")
    items.append(_item("piece_clearance", not bad, f"collisions: {bad}" if bad else "pieces clear of text",
                       "Move decorative elements/shapes off the text blocks. A CTA pill may sit under its own CTA label only."))

    # 4. copy fits its box at a usable size
    small = []
    for t in texts:
        fp = resolve_font_path(str((t.style or {}).get("font") or ""))
        w, h = t.rect[2], t.rect[3]
        fit = fit_text_block(fp, t.content, max(40.0, w * 1024), max(20.0, h * 1024), weight=int((t.style or {}).get("weight") or 400))
        if fit["size"] < MIN_TEXT_PX and len(t.content) > 2:
            small.append(f"{t.role}({fit['size']}px)")
    items.append(_item("text_fit", not small, f"copy too big for its box: {small}" if small else "all copy fits its boxes",
                       "Enlarge the text boxes (or shorten the copy) so every string fits at ≥12px."))

    # 5. contrast contract — text has no box; the bg under it must carry contrast
    weak = []
    for t in texts:
        bg_hex, _ = bg_hex_for(t, brief.bg_fields or [], ps)
        if not bg_hex:
            continue
        ratio = contrast_ratio(str((t.style or {}).get("color") or DEFAULT_TEXT_COLOR), bg_hex)
        if ratio < 4.5:
            weak.append(f"{t.role} {ratio:.1f}:1")
    items.append(_item("contrast_contract", not weak, f"weak contrast: {weak}" if weak else "every font colour reads on its bg field",
                       "Declare a bg_fields colour under each text block (or change the font colour) so contrast is ≥4.5:1."))

    # 6. logo clearspace — logo not covered by other pieces
    logos = [p for p in pieces if "logo" in p.role]
    lc = []
    for lg in logos:
        for p in ps:
            if p is lg or p.kind == "text":
                continue
            if overlaps(lg.rect, p.rect, pad=0.01):
                lc.append(f"{lg.role}×{p.role}")
    items.append(_item("logo_clearspace", not lc, f"logo blocked: {lc}" if lc else "logo has clearspace",
                       "Give the logo clearspace — nothing else may overlap it."))
    return items


def _covers(outer: list[float], inner: list[float], frac: float = 0.85) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    inter = max(0.0, min(ox + ow, ix + iw) - max(ox, ix)) * max(0.0, min(oy + oh, iy + ih) - max(oy, iy))
    return inter >= frac * max(1e-9, iw * ih)


VISION_SYSTEM = """You are a design director reviewing a LAYOUT PROOF: coloured fields = the planned background colour zones; pieces = exact text (in final font colours), brand elements and shapes that will sit on top of a generated background.
Score the LAYOUT only (ignore the flat field colours — the real background will be richer).
Reply ONLY JSON: {"items":[{"check":"hierarchy"|"balance"|"alignment"|"brand_feel"|"crowding", "pass": bool, "note": str, "fix_prompt": str}], "score": 0..100}
- hierarchy: headline dominant, clear reading order.
- balance: composition weight distributed, no dead or crammed corners.
- alignment: text/shapes share sensible margins/axes.
- brand_feel: the layout feels like the brand (colours, logo presence).
- crowding: pieces breathe; nothing jams the edges or each other.
fix_prompt = ONE precise instruction to move/resize a placement when pass=false."""


def vision_check(proof_png: str, brief: Brief) -> CriticReport:
    try:
        raw = llm.chat_vision(
            VISION_SYSTEM,
            [
                {"type": "text", "text": f"Concept: {brief.idea or brief.color_story}\nHeadline: {brief.copy.headline}"},
                llm.img_part(proof_png, detail="high"),
            ],
            model="kimi-latest",
            json_mode=True,
            timeout=60.0,
            attempts=1,
        )
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip() or "{}")
    except Exception as e:
        return CriticReport(score=50.0, items=[_item("vision", False, f"vision judge unavailable: {str(e)[:60]}")])
    items = [
        CriticItem(**{"check": str(i.get("check") or "vision"), "pass": bool(i.get("pass")), "note": str(i.get("note") or ""), "fix_prompt": str(i.get("fix_prompt") or "")})
        for i in data.get("items", [])
        if isinstance(i, dict)
    ]
    score = float(data.get("score") or (100.0 * sum(1 for i in items if i.pass_) / max(1, len(items))))
    return CriticReport(score=max(0.0, min(100.0, score)), items=items)


def judge_layout(proof_png: str, brief: Brief, with_vision: bool = True) -> CriticReport:
    items = det_check(brief)
    score = 100.0 * sum(1 for i in items if i.pass_) / max(1, len(items))
    fixes = [i.fix_prompt for i in items if not i.pass_ and i.fix_prompt]
    if with_vision:
        v = vision_check(proof_png, brief)
        items += v.items
        score = 0.55 * score + 0.45 * v.score
        fixes += [i.fix_prompt for i in v.items if not i.pass_ and i.fix_prompt]
    return CriticReport(score=round(score, 1), items=items, fixes=fixes)


ADJUST_SYSTEM = """You perfect a layout spec. The layout proof failed some checks.
Adjust the spec so ALL checks pass while keeping the design intent (story, copy, colour story).
Output ONLY JSON: {"placements": [...same schema...], "bg_fields": [...same schema...]}
- placements: the FULL new list (kind/role/rect/content/asset_id/style) — never drop the headline/logo/cta.
- rects are fractions [x,y,w,h]; keep every piece inside 0..1; text blocks may not overlap each other or decorative pieces (a CTA pill under its CTA label is legal).
- text style.color must read (≥4.5:1) on its bg field colour (or shape fill) — adjust rect/field/colour accordingly.
- Prefer MOVING/RESIZING over redesigning. Keep exact copy strings and asset_ids."""


def perfect_layout(brief: Brief, proof_png: str, brand_id: str, rounds: int = 2) -> tuple[Brief, list[CriticReport]]:
    """Judge → adjust → re-render → re-judge. Returns the best brief + all reports."""
    from .. import store
    from .canvas import render_layout
    from ..brief.placements import sanitize_fields, sanitize_placements, coordinate

    reports: list[CriticReport] = []
    best, best_score, best_report = brief, -1.0, None
    current = brief
    for rnd in range(max(1, rounds)):
        render_layout(current, proof_png, brand_id=brand_id, mode="proof")
        rep = judge_layout(proof_png, current)
        reports.append(rep)
        if rep.score > best_score:
            best, best_score, best_report = current, rep.score, rep
        if rep.score >= 90 or not rep.fixes:
            break
        if rnd == rounds - 1:
            break
        # reasoning model adjusts the spec against the exact failures
        payload = {
            "failures": [{"check": i.check, "note": i.note, "fix": i.fix_prompt} for i in rep.items if not i.pass_],
            "copy": current.copy.model_dump(),
            "placements": [p.model_dump() for p in current.placements],
            "bg_fields": [f.model_dump() for f in current.bg_fields or []],
        }
        try:
            raw = llm.chat_text(ADJUST_SYSTEM, json.dumps(payload, ensure_ascii=False), model="pro", json_mode=True, timeout=120.0, attempts=2)
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip() or "{}")
        except Exception:
            data = {}
        catalog = store.load_catalog(brand_id) if brand_id else []
        ps, promoted_bg = sanitize_placements(data.get("placements") or [], current.copy, catalog)
        fs = sanitize_fields((data.get("bg_fields") or []) + promoted_bg)
        if not ps:
            break
        ps, _ = coordinate(ps, fs, catalog, store.load_grammar(brand_id))
        current = current.model_copy(update={"placements": ps, "bg_fields": fs or current.bg_fields})
    if best is not current:
        render_layout(best, proof_png, brand_id=brand_id, mode="proof")
    return best, reports
