import json
import re
from pathlib import Path

from .. import llm
from ..models import Asset

CLASSIFY_SYSTEM = """You are a brand-asset librarian. For each image output JSON:
{"items":[{"file": str,
 "kind": "single"|"asset-grid"|"documentation"|"photo-scene"|"ui-shot"|"logo"|"template",
 "name": str, "tags": [str], "colors": [str], "semantic": str, "usage": str,
 "role_hints": [str], "exact_required": bool, "cells": [{"name": str, "semantic": str, "tags": [str]}]}]}
Rules:
- single = one ready-to-use element on plain bg. asset-grid = multiple elements in a labeled/gutter grid (list each cell).
- documentation = guideline/usage page (assets do NOT enter the library from it).
- logo / template / ui-shot / photo-scene as appropriate.
- exact_required = true for logos and anything that must keep pixel identity.
- semantic = meaning words for selection (e.g. "growth", "win", "care", "alert").
- role_hints from: bg, mask, bloom, charm, logo, ui, footer, accent, pattern, text_safe.
- usage = one line on HOW to use per the page itself. colors = dominant hexes."""

NAME_SYSTEM = """Name each cropped grid cell. Reply JSON: {"names":[{"cell": str, "name": str, "semantic": str, "tags": [str]}]}.
Names must match any visible label text under/over the cell if present."""


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


def classify_batch(paths: list[str], source_dir: str) -> list[dict]:
    parts = [{"type": "text", "text": f"Classify these {len(paths)} images."}]
    for p in paths:
        parts.append({"type": "text", "text": f"FILE: {Path(p).name}"})
        parts.append(llm.img_part(p, detail="low"))
    raw = llm.chat_vision(CLASSIFY_SYSTEM, parts, model="flash", json_mode=True)
    items = _parse_json(raw).get("items", [])
    for it in items:
        it["source"] = source_dir
    return items


def name_cells(parent_png: str, cell_pngs: list[str]) -> dict[str, dict]:
    parts = [{"type": "text", "text": f"Parent sheet: {Path(parent_png).name}. Name these cells."}]
    parts.append(llm.img_part(parent_png, detail="high"))
    for p in cell_pngs:
        parts.append({"type": "text", "text": f"CELL: {Path(p).stem}"})
        parts.append(llm.img_part(p, detail="high"))
    raw = llm.chat_vision(NAME_SYSTEM, parts, model="flash", json_mode=True)
    out = {}
    for n in _parse_json(raw).get("names", []):
        out[n.get("cell", "")] = n
    return out


def _as_str(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v or "")


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return [_as_str(x) for x in v]
    return [_as_str(v)] if v else []


def item_to_asset(item: dict, png: str, asset_id: str) -> Asset:
    kind_map = {
        "single": "single",
        "asset-grid": "grid-cell",
        "documentation": "doc",
        "photo-scene": "photo-scene",
        "ui-shot": "ui-shot",
        "logo": "logo",
        "template": "template",
    }
    kind = kind_map.get(item.get("kind", "single"), "single")
    if kind == "single":
        tags = item.get("tags", [])
        low = " ".join(tags).lower()
        if "charm" in low or "icon" in low:
            kind = "charm"
        elif "bloom" in low or "shape" in low:
            kind = "bloom"
        elif "illustration" in low:
            kind = "illustration"
    return Asset(
        id=asset_id,
        name=_as_str(item.get("name", asset_id)),
        kind=kind,
        tags=_as_list(item.get("tags")),
        colors=_as_list(item.get("colors")),
        usage=_as_str(item.get("usage")),
        role_hints=_as_list(item.get("role_hints")),
        semantic=_as_str(item.get("semantic")),
        png=png,
        source=_as_str(item.get("source")),
        directly_usable=kind != "doc",
        exact_required=bool(item.get("exact_required")) or kind in ("logo", "charm", "ui-shot"),
    )
