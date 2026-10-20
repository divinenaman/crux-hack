"""Asset classification for the layout-first canvas.

Every brand asset is classed as:
  element   — directly placeable (logo, charm, icon, shape, UI card). Often comes
              in several COLOURWAYS (white/navy/blue…); colourway variants of one
              element share a `colorway_group` so the planner can pick the variant
              that coordinates with the background it will sit on.
  reference — full images / scenes / templates: inspiration + palette examples
              ONLY. Never placed on the canvas.

Works two ways:
  - fresh ingest: the vision classifier proposes cls/colorway, we normalize;
  - existing catalogs: deterministic derivation from kind/name/colors (migration).
"""
from __future__ import annotations

import re

from ..models import Asset, Grammar

REFERENCE_KINDS = {"photo-scene", "template", "doc"}
ELEMENT_KINDS = {"logo", "charm", "bloom", "illustration", "single", "grid-cell", "vector", "ui-shot"}

_COLORWAY_TOKENS = (
    "white",
    "navy",
    "dark",
    "light",
    "black",
    "blue",
    "sky",
    "pink",
    "green",
    "yellow",
    "mono",
    "grey",
    "gray",
    "purple",
    "orange",
    "red",
    "teal",
    "cyan",
    "magenta",
    "gold",
)

_STOP_NAME_TOKENS = {
    "logo",
    "wordmark",
    "icon",
    "charm",
    "shape",
    "asset",
    "element",
    "the",
    "a",
    "an",
    "and",
    "with",
    "for",
    "on",
    "in",
    "of",
    "primary",
    "secondary",
    "alternate",
    "version",
    "variant",
    "colourway",
    "colorway",
    "colour",
    "color",
    *_COLORWAY_TOKENS,
}


def cls_of(asset: Asset) -> str:
    """element (placeable) vs reference (inspiration only)."""
    if asset.kind in REFERENCE_KINDS:
        return "reference"
    if (asset.usage or "").lower().startswith("extracted"):
        return "element"
    if asset.kind in ELEMENT_KINDS:
        # a full ad/template-like single with body text is a reference, not a stamp
        if asset.kind in ("single", "illustration") and len(asset.texts or []) >= 3:
            return "reference"
        return "element"
    return "element"


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 1]


def colorway_of(asset: Asset) -> tuple[str, str]:
    """(colorway, colorway_group) for an element.

    colorway from the name token ("Xero logo white" → white) or, failing that,
    the dominant colour's family ("#000856" → navy). group = the element's name
    with colour tokens stripped — colourway variants collapse onto one key.
    """
    toks = _name_tokens(asset.name)
    colorway = ""
    for t in toks:
        if t in _COLORWAY_TOKENS:
            colorway = t
            break
    if not colorway and asset.colors:
        colorway = _color_family(asset.colors[0])
    group_toks = [t for t in toks if t not in _STOP_NAME_TOKENS]
    group = "_".join(group_toks[:4]) or re.sub(r"[^a-z0-9]+", "_", (asset.name or asset.id).lower()).strip("_")
    if asset.kind == "logo":
        group = f"logo_{group}"
    return colorway, group


def _color_family(hexv: str) -> str:
    try:
        h = (hexv or "").lstrip("#")
        if len(h) < 6:
            return ""
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return ""
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 50:
        return "black"
    if mn > 200:
        return "white"
    if mx - mn < 24:
        return "dark" if mx < 140 else "light"
    if b >= r and b >= g:
        return "navy" if mx < 120 else "blue"
    if r >= g and r >= b:
        return "pink" if b > g else "red"
    return "green"


def enrich_classification(assets: list[Asset], grammar: Grammar | None = None) -> list[Asset]:
    """Stamp cls/colorway/colorway_group on every asset (idempotent)."""
    for a in assets:
        a.cls = cls_of(a)
        if a.cls == "element":
            cw, group = colorway_of(a)
            a.colorway = cw
            a.colorway_group = group
        else:
            a.colorway = a.colorway or ""
            a.colorway_group = a.colorway_group or ""
    return assets


def colorway_siblings(assets: list[Asset], asset: Asset) -> list[Asset]:
    """Every colourway variant of this element (including itself)."""
    if not asset.colorway_group:
        return [asset]
    return [a for a in assets if a.cls == "element" and a.colorway_group == asset.colorway_group]


def pick_colorway(assets: list[Asset], asset: Asset, want_hex: str = "", dark_bg: bool = False) -> Asset:
    """Pick the colourway of this element that reads on the planned background.

    dark_bg → prefer light colourways (white/light/sky); else prefer dark ones.
    want_hex → closest dominant colour wins.
    """
    sibs = colorway_siblings(assets, asset)
    if len(sibs) == 1 or (not want_hex and not dark_bg):
        return asset

    def _score(a: Asset) -> float:
        s = 0.0
        cw = (a.colorway or "").lower()
        if dark_bg and cw in ("white", "light", "sky", "cyan", "yellow", "gold"):
            s += 3.0
        if not dark_bg and cw in ("navy", "dark", "black", "blue", "purple"):
            s += 3.0
        if want_hex and a.colors:
            s += 2.0 - min(2.0, _hex_distance(want_hex, a.colors[0]) / 96.0)
        return s

    return max(sibs, key=_score)


def _hex_distance(a: str, b: str) -> float:
    try:
        ha = (a or "").lstrip("#")
        hb = (b or "").lstrip("#")
        if len(ha) < 6 or len(hb) < 6:
            return 999.0
        return sum(abs(int(ha[i : i + 2], 16) - int(hb[i : i + 2], 16)) for i in (0, 2, 4))
    except ValueError:
        return 999.0


def pick_palette_refs(assets: list[Asset], grammar: Grammar, k: int = 4) -> list[str]:
    """Reference assets that best exemplify the brand palette in use.

    These feed the planner (colour-story examples) and the fill prompt — the
    'what does this brand's colour world look like' evidence.
    """
    refs = [a for a in assets if a.cls == "reference" and a.png]
    if not refs:
        refs = [a for a in assets if a.kind in REFERENCE_KINDS and a.png]
    palette = [p.get("hex", "") for p in (grammar.palette or []) if p.get("hex")]
    if not palette:
        return [a.id for a in sorted(refs, key=lambda a: -(a.quality or {}).get("score", 0))[:k]]

    def _score(a: Asset) -> float:
        hit = sum(1 for c in (a.colors or []) if any(_hex_distance(c, p) < 70 for p in palette))
        q = (a.quality or {}).get("score", 0) / 100.0
        return hit * 2.0 + q

    ranked = sorted(refs, key=_score, reverse=True)
    return [a.id for a in ranked[:k] if _score(a) > 0] or [a.id for a in ranked[:k]]
