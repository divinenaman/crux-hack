import json
import re
from pathlib import Path

from .. import llm
from ..models import Asset

CLASSIFY_SYSTEM = """You are a brand-asset librarian. For each image output JSON:
{"items":[{"file": str,
 "kind": "single"|"asset-grid"|"documentation"|"photo-scene"|"ui-shot"|"logo"|"template",
 "name": str, "tags": [str], "colors": [str], "semantic": str, "usage": str,
 "role_hints": [str], "exact_required": bool, "cells": [{"name": str, "semantic": str, "tags": [str]}],
  "extractions": [{"name": str, "role": "logo"|"charm"|"ui"|"bloom"|"photo"|"accent", "bbox": [x,y,w,h] 0..1 fractions, "semantic": str, "tags": [str]}],
  "texts": [{"text": str, "role": "headline"|"sub"|"body"|"cta"|"label"|"other", "bbox": [x,y,w,h] 0..1 fractions}]}]}
Rules:
- single = one ready-to-use element on plain bg. asset-grid = multiple elements in a labeled/gutter grid (list each cell).
- documentation = guideline/usage page (assets do NOT enter the library from it).
- logo / template / ui-shot / photo-scene as appropriate.
- exact_required = true for logos and anything that must keep pixel identity.
- semantic = meaning words for selection (e.g. "growth", "win", "care", "alert").
- role_hints from: bg, mask, bloom, charm, logo, ui, footer, accent, pattern, text_safe.
- usage = one line on HOW to use per the page itself. colors = dominant hexes.
- extractions = distinct elements INSIDE a composed/full image worth harvesting as separate reusable assets (logo/wordmark, character, icon/charm, product UI card, decorative shape). bbox must be TIGHT: the element fills at least 70% of the box — no surrounding scene, no generous padding. max 5 per image. EMPTY list for simple standalone elements.
- texts = EVERY readable text block written in the image, transcribed EXACTLY as written (even stylised/short labels), with a tight bbox. This inventory makes the ref's text replaceable later. EMPTY list only when the image has no text."""

NAME_SYSTEM = """Name each cropped grid cell. Reply JSON: {"names":[{"cell": str, "name": str, "semantic": str, "tags": [str]}]}.
Names must match any visible label text under/over the cell if present."""

TIGHTEN_SYSTEM = """The image is a LOOSE crop of ONE named element, possibly with surrounding junk.
Return the TIGHT bounding box of JUST the named element in ABSOLUTE PIXELS of this image.
Reply JSON only: {"bbox": [x, y, w, h]}  (x,y = top-left pixel; w,h = size in pixels).
Rules:
- the named element fills 85%+ of the box; exclude EVERY other object (people, coins, badges, scenery).
- never cut INTO the element: bbox may extend to the image edges (0 or {W}/{H}).
- if multiple similar logos/objects exist, pick only the one the name describes."""

TIGHTEN_RETRY = """Your previous box still includes junk or is the wrong size. Look again.
Crop is {W}x{H} px. Named element ONLY: "{name}". Other objects in the frame must be OUTSIDE the box.
Reply JSON only: {"bbox": [x, y, w, h]} in ABSOLUTE PIXELS."""

TIGHTEN_CRITIQUE = """You proposed bbox {proposed} (px) for element "{name}" in this {W}x{H} px image.
Double-check your own answer:
(a) the element is FULLY inside the box — not cut through at any edge;
(b) no OTHER objects (people, coins, badges, scenery, extra text) are inside the box.
If either fails, return the corrected bbox. If it is already perfect, return the same box.
Reply JSON only: {"bbox": [x, y, w, h]} in ABSOLUTE PIXELS."""


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            # truncated reply — salvage every complete "key": value pair we can
            out: dict = {}
            for k, v in re.findall(r'"(\w+)"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|\[[^\]]*\]|true|false|null)', m.group(0)):
                try:
                    out[k] = json.loads(v)
                except json.JSONDecodeError:
                    continue
            return out


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


def tighten_one(png: str, name: str) -> list[float] | None:
    """Tighten one loose crop to its named element. Returns [x,y,w,h] fractions of the crop."""
    from PIL import Image

    try:
        W, H = Image.open(png).size
    except Exception:
        return None
    if W < 16 or H < 16:
        return None

    def _ask(sys: str, user: str) -> list[float] | None:
        bb = None
        prev = ""
        for _ in range(2):
            try:
                # kimi-latest: the only budget-available model with reliable spatial bboxes
                raw = llm.chat_vision(sys, [{"type": "text", "text": user + prev}, llm.img_part(png, detail="high")], model="kimi-latest", json_mode=True, timeout=45.0, attempts=1)
            except Exception:
                return bb
            cand = _parse_json(raw).get("bbox")
            if isinstance(cand, list) and len(cand) == 4:
                try:
                    bb = [float(v) for v in cand]
                except (TypeError, ValueError):
                    bb = None
                if bb:
                    break
            prev = ' Previous reply was not valid JSON with a 4-number "bbox". Reply ONLY {"bbox":[x,y,w,h]}.'
        return bb

    def _to_frac(box: list[float]) -> list[float] | None:
        # pixel space → fractions; tolerate a model that answers in fractions anyway
        x, y, w, h = box
        if max(abs(x), abs(y), abs(w), abs(h)) > 1.5:
            x, y, w, h = x / W, y / H, w / W, h / H
        x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
        w, h = max(0.0, min(1.0 - x, w)), max(0.0, min(1.0 - y, h))
        return [x, y, w, h] if w > 0.01 and h > 0.01 else None

    raw_bb = _ask(TIGHTEN_SYSTEM.replace("{W}", str(W)).replace("{H}", str(H)), f'Element name: "{name}". This crop is {W}x{H} px.')
    bb = _to_frac(raw_bb) if raw_bb else None
    # second opinion: catch boxes that cut the element or swallow neighbors
    if raw_bb:
        proposed = [round(v, 1) for v in raw_bb]
        crit_sys = (
            TIGHTEN_CRITIQUE.replace("{W}", str(W))
            .replace("{H}", str(H))
            .replace("{proposed}", str(proposed))
            .replace("{name}", name)
        )
        raw2 = _ask(crit_sys, f'Element name: "{name}". Verify your box.')
        bb2 = _to_frac(raw2) if raw2 else None
        if bb2 and 0.02 <= bb2[2] * bb2[3] <= 0.9:
            bb = bb2
    if bb:
        area = bb[2] * bb[3]
        if area > 0.9 or area < 0.02:
            return None
    return bb


def tighten_crops(crops: list[tuple[str, str, str]]) -> dict[str, list[float]]:
    """crops = [(crop_id, png_path, element_name)] → {crop_id: [x,y,w,h]} fractions of crop."""
    out: dict[str, list[float]] = {}
    for cid, png, name in crops:
        bb = tighten_one(png, name)
        if bb:
            out[cid] = bb
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
        texts=[t for t in (item.get("texts") or []) if isinstance(t, dict) and t.get("text")],
        directly_usable=kind != "doc",
        exact_required=bool(item.get("exact_required")) or kind in ("logo", "charm", "ui-shot"),
    )
