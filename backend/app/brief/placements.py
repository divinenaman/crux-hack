"""Placement spec helpers — the layout-first canvas contract.

A design is a list of Placements (text / image / shape) on a blank canvas plus
BgFields (colour-control regions for the background fill). Text carries only a
font colour — never a box — so every text placement MUST sit on a bg field that
carries its contrast. `coordinate()` enforces that pair deterministically and
picks the colourway of each element that reads on its planned field.

Deterministic composition runs through archetype skeletons (`_SKELETONS`) —
diagonal tension / poster centre / split world — so even the no-LLM path
produces designed, asymmetric layouts instead of one safe stack.
"""
from __future__ import annotations

import re

from ..models import Asset, BgField, CopyBlock, Grammar, Placement
from ..ingest.groups import pick_colorway

RATIO_SIZE = {"1:1": (1024, 1024), "4:5": (1024, 1280), "9:16": (1024, 1536), "16:9": (1536, 1024)}


# ---------- colour math (WCAG-ish) ----------


def _rgb(hexv: str) -> tuple[float, float, float] | None:
    try:
        h = (hexv or "").strip().lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) < 6:
            return None
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def rel_luminance(hexv: str) -> float | None:
    rgb = _rgb(hexv)
    if not rgb:
        return None
    def _ch(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (_ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = rel_luminance(a), rel_luminance(b)
    if la is None or lb is None:
        return 0.0
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(hexv: str) -> bool:
    lum = rel_luminance(hexv)
    return (lum if lum is not None else 1.0) < 0.35


def best_text_on(bg_hex: str, prefer: str = "") -> str:
    """White or near-black — whichever reads on bg_hex (prefer wins ties)."""
    white, ink = "#FFFFFF", "#111111"
    cw, ci = contrast_ratio(white, bg_hex), contrast_ratio(ink, bg_hex)
    if prefer:
        cp = contrast_ratio(prefer, bg_hex)
        if cp >= 4.5:
            return prefer
    return white if cw >= ci else ink


def _intent_hex(intent: str, color: str = "") -> str | None:
    """Resolve a bg-field intent to a concrete hex when it names/holds one."""
    if color and _rgb(color):
        return color
    m = re.search(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})", intent or "")
    if m:
        return m.group(0)
    return None


def field_dark(field: BgField | None, default_light: bool = True) -> bool:
    """Is the planned field under an element dark?"""
    if not field:
        return not default_light
    hx = _intent_hex(field.intent, field.color)
    if hx:
        return is_dark(hx)
    words = (field.intent or "").lower()
    if any(w in words for w in ("dark", "navy", "black", "deep", "midnight", "charcoal", "shadow")):
        return True
    if any(w in words for w in ("light", "cream", "white", "pale", "soft", "pastel", "sky")):
        return False
    return not default_light


def field_for(rect: list[float], fields: list[BgField]) -> BgField | None:
    """The bg field with the most overlap over rect — ties go to the SMALLER
    (more specific) field, so a colour pool beats a full-canvas base field.
    Centre-point fallback."""
    x, y, w, h = [float(v) for v in rect]
    cx, cy = x + w / 2, y + h / 2
    best, best_area, best_size = None, 0.0, float("inf")
    for f in fields:
        fx, fy, fw, fh = [float(v) for v in f.rect]
        ox = max(0.0, min(x + w, fx + fw) - max(x, fx))
        oy = max(0.0, min(y + h, fy + fh) - max(y, fy))
        area = ox * oy
        size = fw * fh
        if area > best_area or (area == best_area and area > 0 and size < best_size):
            best, best_area, best_size = f, area, size
    if best:
        return best
    for f in fields:
        fx, fy, fw, fh = [float(v) for v in f.rect]
        if fx <= cx <= fx + fw and fy <= cy <= fy + fh:
            return f
    return None


# ---------- spec sanitizing + coordination ----------


_ROLES_TEXT = {"headline", "text_headline", "sub", "text_sub", "subhead", "body", "text_body", "cta", "footer", "legal"}


def content_for(copy: CopyBlock, role: str, content: str = "") -> str:
    r = role.replace("text_", "")
    if r == "headline":
        return copy.headline
    if r in ("sub", "subhead"):
        return copy.sub
    if r == "body":
        return "\n".join(copy.body)
    if r == "cta":
        return copy.cta
    return content or ""


def _clamp_rect(r: list[float], bleed: bool = True) -> list[float] | None:
    try:
        x, y, w, h = [float(v) for v in r]
    except (TypeError, ValueError):
        return None
    # non-text pieces may bleed slightly past the edge (designed crop);
    # text always stays fully inside so glyphs never clip
    margin = 0.02 if bleed else 0.0
    x, y = max(-margin, min(1.0 + margin, x)), max(-margin, min(1.0 + margin, y))
    w, h = max(0.01, min(1.0 + margin - x, w)), max(0.01, min(1.0 + margin - y, h))
    return [x, y, w, h]


def sanitize_placements(raw: list, copy: CopyBlock, catalog: list[Asset]) -> list[Placement]:
    """Validate LLM placement JSON into Placement models (drop junk)."""
    by_id = {a.id: a for a in catalog}
    out: list[Placement] = []
    seen_assets: set[str] = set()
    seen_text: set[tuple[str, str]] = set()
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        kind = str(p.get("kind") or "").lower()
        role = str(p.get("role") or "").strip()
        if kind not in ("text", "image", "shape") or not role:
            continue
        rect = _clamp_rect(p.get("rect") or [], bleed=kind != "text")
        if not rect:
            continue
        style = p.get("style") if isinstance(p.get("style"), dict) else {}
        content = str(p.get("content") or "")
        asset_id = str(p.get("asset_id") or "")
        if kind == "text":
            content = content_for(copy, role, content)
            if not content.strip():
                continue
            key = (role.replace("text_", ""), content)
            if key in seen_text:
                continue  # duplicate text piece (role variants both map to copy) — drop
            seen_text.add(key)
            style.pop("rotation", None)  # never tilt type
        if kind == "image":
            a = by_id.get(asset_id)
            if not a or not a.png:
                continue
            if asset_id in seen_assets:
                continue  # never stamp the same asset twice in one design
            seen_assets.add(asset_id)
        if kind == "shape":
            sh = str(style.get("shape") or "rect").lower()
            if sh not in ("rect", "circle", "pill"):
                style["shape"] = "rect"
        out.append(Placement(kind=kind, role=role, rect=rect, content=content, asset_id=asset_id, style=style))
    return out


def sanitize_fields(raw: list) -> list[BgField]:
    out: list[BgField] = []
    for f in raw or []:
        if not isinstance(f, dict):
            continue
        rect = _clamp_rect(f.get("rect") or [])
        if not rect:
            continue
        out.append(
            BgField(
                rect=rect,
                intent=str(f.get("intent") or ""),
                color=str(f.get("color") or ""),
                why=str(f.get("why") or ""),
            )
        )
    return out


def _overlap_area(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return ox * oy


def bg_hex_for(p: Placement, fields: list[BgField], placements: list[Placement]) -> tuple[str | None, bool]:
    """Concrete bg colour under a placement + whether that bg is dark.

    A shape sitting under the text IS its background (CTA pill) — otherwise the
    governing bg field. Returns (hex|None, dark).
    """
    best_shape, best_area = None, 0.0
    for s in placements:
        if s.kind != "shape" or s is p:
            continue
        area = _overlap_area(p.rect, s.rect)
        if area > best_area and area >= 0.4 * max(1e-6, p.rect[2] * p.rect[3]):
            best_shape, best_area = s, area
    if best_shape is not None:
        fill = str(best_shape.style.get("fill") or "")
        if _rgb(fill):
            return fill, is_dark(fill)
    f = field_for(p.rect, fields)
    hx = _intent_hex(f.intent, f.color) if f else None
    if hx:
        return hx, is_dark(hx)
    return None, field_dark(f, default_light=True)


def coordinate(placements: list[Placement], fields: list[BgField], catalog: list[Asset], grammar: Grammar) -> tuple[list[Placement], list[str]]:
    """Colour coordination — the contract that keeps text readable and elements
    of a piece with their background:

    1. every text placement gets a font colour that reads on the bg under it
       (shape fill or field — planner preference kept when it passes ≥4.5:1);
    2. every image placement gets the colourway of its element that reads on
       the field it sits on (dark field → light colourway, …);
    3. shape fills are nudged to contrast when they carry text-free decoration.
    """
    notes: list[str] = []
    by_id = {a.id: a for a in catalog}
    palette = [p.get("hex", "") for p in (grammar.palette or []) if p.get("hex")]
    out: list[Placement] = []

    for p in placements:
        bg_hex, dark = bg_hex_for(p, fields, placements)
        st = dict(p.style or {})

        if p.kind == "text":
            prefer = str(st.get("color") or "")
            if bg_hex:
                chosen = best_text_on(bg_hex, prefer)
                if prefer and chosen != prefer and contrast_ratio(prefer, bg_hex) < 4.5:
                    notes.append(f"{p.role}: font colour {prefer} → {chosen} (contrast on {bg_hex})")
                st["color"] = chosen
            else:
                st["color"] = prefer or ("#FFFFFF" if dark else "#000856" if "#000856" in palette else "#111111")
            st.setdefault("align", "center" if p.role == "cta" else "left")
            st.setdefault("weight", 700 if p.role.replace("text_", "") in ("headline", "cta") else 400)
            st.setdefault("lineHeight", 1.15)
            st["draw_bg"] = False  # policy: text never sits in a box — font colour only
            out.append(p.model_copy(update={"style": st}))
            continue

        if p.kind == "image":
            a = by_id.get(p.asset_id)
            if not a:
                out.append(p)
                continue
            best = pick_colorway(catalog, a, want_hex="", dark_bg=dark)
            if best.id != p.asset_id:
                notes.append(f"{p.role}: colourway {a.name} → {best.name} ({'light' if dark else 'dark'} field)")
            st.setdefault("fit", "contain")
            out.append(p.model_copy(update={"asset_id": best.id, "style": st}))
            continue

        # shape
        if not st.get("fill") and palette:
            st["fill"] = "#FFFFFF" if dark else palette[0]
        if st.get("fill"):
            st.setdefault("stroke", "")
        out.append(p.model_copy(update={"style": st}))

    return out, notes


def overlaps(a: list[float], b: list[float], pad: float = 0.0) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + pad <= bx or bx + bw + pad <= ax or ay + ah + pad <= by or by + bh + pad <= ay
    )


def first_free_rect(candidates: list[list[float]], taken: list[list[float]], pad: float = 0.02) -> list[float] | None:
    for r in candidates:
        if all(not overlaps(r, t, pad) for t in taken):
            return r
    return None


# ---------- deterministic archetype skeletons ----------
#
# Each skeleton is a COMPOSED layout: staggered margins, scale drama, one
# deliberate rule-break (bleed / seam-crossing / tilt), a planned pool of calm.
# Token colours ("@ink", "@palette0") resolve against the brand grammar.

_SKELETONS: dict[str, dict] = {
    "diagonal_tension": {
        "fields": [
            ([0.0, 0.0, 1.0, 0.5], "warm cream calm field (near #F5F3EC)", "#F5F3EC", "headline + sub sit here"),
            ([0.0, 0.5, 1.0, 0.5], "deep brand-colour field, smooth continuation", "@palette0", "white body + cta counterweight"),
        ],
        "pieces": [
            ("text", "headline", [0.07, 0.05, 0.55, 0.28], {"align": "left", "weight": 700}),
            ("text", "sub", [0.45, 0.35, 0.46, 0.07], {"align": "left", "weight": 400}),
            ("text", "body", [0.52, 0.55, 0.4, 0.12], {"align": "left", "weight": 400}),
            ("shape", "cta_pill", [0.08, 0.74, 0.32, 0.1], {"shape": "pill", "fill": "@ink", "stroke": "", "radius": 999}),
            ("text", "cta", [0.1, 0.755, 0.28, 0.07], {"align": "center", "weight": 700}),
        ],
        "logo": [0.84, 0.86, 0.2, 0.11],  # rule-break: bleeds past the right edge
        "zones": [[0.64, 0.0, 0.38, 0.32], [0.0, 0.38, 0.36, 0.3], [0.5, 0.7, 0.4, 0.28]],
    },
    "poster_center": {
        "fields": [
            ([0.0, 0.0, 1.0, 1.0], "warm cream calm field (near #F5F3EC)", "#F5F3EC", "giant centred statement sits here"),
            ([0.5, 0.6, 0.5, 0.14], "deep navy pool", "@palette0", "white body line sits here"),
        ],
        "pieces": [
            ("text", "headline", [0.08, 0.2, 0.84, 0.3], {"align": "center", "weight": 700}),
            ("text", "sub", [0.25, 0.52, 0.5, 0.06], {"align": "center", "weight": 400}),
            ("text", "body", [0.55, 0.62, 0.36, 0.1], {"align": "left", "weight": 400}),
            ("shape", "cta_pill", [0.35, 0.82, 0.3, 0.09], {"shape": "pill", "fill": "@ink", "stroke": "", "radius": 999}),
            ("text", "cta", [0.37, 0.835, 0.26, 0.06], {"align": "center", "weight": 700}),
        ],
        "logo": [0.05, 0.05, 0.14, 0.08],  # tiny stamp, top-left
        "zones": [[-0.02, 0.6, 0.3, 0.38], [0.72, 0.0, 0.3, 0.18], [0.88, 0.35, 0.14, 0.24]],
    },
    "split_world": {
        "fields": [
            ([0.0, 0.0, 0.4, 1.0], "deep brand-colour half", "@palette0", "logo + element mass half"),
            ([0.4, 0.0, 0.6, 1.0], "warm cream calm half (near #F5F3EC)", "#F5F3EC", "type half — headline + sub + body"),
        ],
        "pieces": [
            ("text", "headline", [0.44, 0.06, 0.5, 0.3], {"align": "left", "weight": 700}),
            ("text", "sub", [0.44, 0.4, 0.42, 0.07], {"align": "left", "weight": 400}),
            ("text", "body", [0.46, 0.5, 0.38, 0.12], {"align": "left", "weight": 400}),
            ("shape", "cta_pill", [0.44, 0.8, 0.3, 0.09], {"shape": "pill", "fill": "@ink", "stroke": "", "radius": 999}),
            ("text", "cta", [0.46, 0.815, 0.26, 0.06], {"align": "center", "weight": 700}),
        ],
        "logo": [0.06, 0.06, 0.18, 0.1],
        "zones": [[0.06, 0.42, 0.34, 0.32], [0.86, 0.5, 0.16, 0.24], [0.04, 0.78, 0.28, 0.2]],  # zone[0] crosses the seam
    },
}


def element_zones(archetype: str) -> list[list[float]]:
    sk = _SKELETONS.get(archetype) or _SKELETONS["diagonal_tension"]
    return [list(r) for r in sk["zones"]]


def fallback_placements(copy: CopyBlock, grammar: Grammar, catalog: list[Asset], archetype: str = "diagonal_tension") -> tuple[list[Placement], list[BgField]]:
    """Deterministic COMPOSED layout when the planner returns nothing usable.

    Rotating archetype skeletons (diagonal tension / poster centre / split
    world) — staggered margins, scale drama, one designed rule-break each —
    instead of one safe corporate stack. Contrast contract declared as bg
    fields; `coordinate()` settles every font/element colour.
    """
    sk = _SKELETONS.get(archetype) or _SKELETONS["diagonal_tension"]
    palette = [p.get("hex", "") for p in (grammar.palette or []) if p.get("hex")]
    ink = "#000856" if "#000856" in palette else (palette[0] if palette else "#111111")

    def _fill(tok: str, default: str) -> str:
        return {"@ink": ink, "@palette0": palette[0] if palette else default, "@white": "#FFFFFF"}.get(tok, tok or default)

    fields = [
        BgField(rect=list(r), intent=intent, color=_fill(col, "#F5F3EC"), why=why)
        for (r, intent, col, why) in sk["fields"]
    ]
    placements: list[Placement] = []
    for kind, role, rect, style in sk["pieces"]:
        st = dict(style)
        if kind == "shape" and str(st.get("fill") or "").startswith("@"):
            st["fill"] = _fill(str(st["fill"]), ink)
        content = content_for(copy, role) if kind == "text" else ""
        placements.append(Placement(kind=kind, role=role, rect=list(rect), content=content, style=st))
    logo = next((a for a in catalog if a.cls == "element" and a.kind == "logo"), None)
    if logo:
        placements.append(Placement(kind="image", role="logo", rect=list(sk["logo"]), asset_id=logo.id, style={"fit": "contain"}))
    return placements, fields


def placements_from_zones(zones: list, copy: CopyBlock) -> tuple[list[Placement], list[BgField]]:
    """Legacy bridge: old wireframe zones → layout placements (deep planner path)."""
    out: list[Placement] = []
    for z in zones or []:
        role = str(getattr(z, "role", "") or "")
        rect = list(getattr(z, "rect", []) or [])
        r = _clamp_rect(rect)
        if not r:
            continue
        rr = role.replace("text_", "")
        if rr in ("headline", "sub", "subhead", "body", "cta", "footer"):
            content = content_for(copy, role)
            if content.strip():
                out.append(Placement(kind="text", role=rr, rect=r, content=content, style={"color": "#000856", "draw_bg": False}))
    fields = [
        BgField(rect=[0.0, 0.0, 1.0, 1.0], intent="light neutral field", color="#F5F3EC", why="legacy zone layout — single field"),
    ]
    return out, fields


_DEFAULT_ZONES = [
    [0.6, 0.06, 0.34, 0.28],
    [0.58, 0.38, 0.36, 0.32],
    [0.4, 0.7, 0.24, 0.2],
    [0.62, 0.72, 0.3, 0.22],
]


def place_element_rects(n: int, taken: list[list[float]], zones: list[list[float]] | None = None) -> list[list[float]]:
    """n overlap-free element rects against the given occupied boxes (text/shapes),
    from the archetype's zones (or the default right-side bins)."""
    out: list[list[float]] = []
    occ = list(taken)
    for r in (zones or _DEFAULT_ZONES):
        if len(out) >= n:
            break
        pick = first_free_rect([r] + [[min(0.95, r[0] + 0.02 * i), r[1], r[2], r[3]] for i in range(1, 4)], occ)
        if pick:
            out.append(pick)
            occ.append(pick)
    return out
