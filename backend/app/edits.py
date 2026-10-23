"""Prompt → typed layer instructions → deterministic appliers.

The user's edit request is converted by the agent into a list of ops against
the layered manifest (background raster + live text/image/shape layers):

    edit · remove · reposition · change_text · change_asset · change_color
    change_background · add_asset

Layer ops mutate the manifest in code. `change_background` re-prompts the image
model the same way generation does: the UPDATED layers render as a wireframe
(reference) + a prompt describing the new artwork and the colour fields to
leave under the pieces. The pieces stay live layers — nothing is baked.
"""
import json
import re
from pathlib import Path

from . import llm
from .models import Manifest

OPS = {
    "edit",
    "remove",
    "reposition",
    "change_text",
    "add_text",
    "change_asset",
    "change_color",
    "change_background",
    "add_asset",
}

_BG_FORBID = (
    "Draw NO text, letters, numbers, words, logos, watermarks, signatures, brand names, "
    "UI text or captions of any kind — the model gets lettering wrong, and the real copy "
    "is pasted on top afterwards. Everything else is drawable: people, faces, hands, "
    "characters, products, devices, food, plants, rooms, streets, objects and floating "
    "illustration accents."
)


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group(0)) if m else {}


EDIT_SYSTEM = """You convert a user's edit request on a LAYERED AD into typed instructions against its layers.
You are a creative director: YOU decide what the new copy and pieces should be — never echo the instruction.
Output ONLY JSON: {"ops": [op, ...]} — ops in application order.
Ops (use these exact "op" values):
- {"op":"change_text","role":str,"content":str,"mode":"verbatim"|"generated"}  rewrite copy (content = exact final string, full joined body for body)
- {"op":"add_text","role":str,"content":str,"mode":"verbatim"|"generated","rect":[x,y,w,h],"color":"#RRGGBB"?}  add a NEW copy block
- {"op":"change_color","role":str,"color":"#RRGGBB"}  recolour a text or shape layer
- {"op":"reposition","role":str,"rect":[x,y,w,h]}  move/resize a layer (fractions 0..1 of canvas)
- {"op":"change_asset","role":str,"asset_id":str,"query":str,"rect":[x,y,w,h]?}  swap the brand asset on an existing image layer
- {"op":"add_asset","asset_id":str,"query":str,"role":str,"rect":[x,y,w,h]}  place a KNOWN brand element from the catalog
- {"op":"remove","role":str}  delete a layer
- {"op":"edit","role":str,"content":str?,"mode":"verbatim"|"generated"?,"color":str?,"rect":[x,y,w,h]?,"asset_id":str?,"query":str?,"size_scale":float?}  partial restyle of one layer
- {"op":"change_background","prompt":str}  repaint the BACKGROUND artwork (at most one)
COPY — verbatim vs generated:
- If the user supplies EXACT copy (typically quoted, e.g. change headline to 'Books done.'), use it verbatim: content = that string, mode="verbatim".
- If the user describes a change in tone / style / intent (e.g. "make the headline quirky", "punchier", "more playful"), YOU write the new copy: content = your finished piece of copy that embodies the instruction — short, on-brand, campaign-ready. mode="generated".
- NEVER put an instruction fragment in content ("quirky" alone is not a headline — write the quirky headline).
Assets:
- The full brand catalog is listed in the context ("assets" — id, name, description). When adding or swapping a brand thing, pick from it and put the id in "asset_id" (keep "query" = your search phrase).
- To SEE what an asset looks like before choosing, call read_asset(asset_id) — it returns the image. View 2–4 candidates, then decide — always put the chosen asset's id in "asset_id". Never answer without an asset_id when placing or swapping an asset.
- "role" must be one of the layer roles provided — except add_text / add_asset, where you choose a short new role.
Contrast (the readability judgement will enforce this too):
- When you recolour a container that carries a label (cta_pill ↔ cta), also recolour the label for contrast (e.g. navy pill ⇒ white cta text) in the same ops.
- Prefer specific layer ops over change_background. Use change_background ONLY when the user wants the artwork / scene / mood / background colours themselves changed. Its prompt describes the scene to draw — people, products, objects and illustration elements are ALL drawable — but must never ask for text, letters, logos or UI.
- Several ops allowed. Empty list only if the request is impossible."""

_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read_asset",
        "description": "View a brand asset image by id (from the catalog in context). Returns the picture so you can see it before choosing. Try different assets until one fits.",
        "parameters": {
            "type": "object",
            "properties": {"asset_id": {"type": "string", "description": "the asset id from the catalog"}},
            "required": ["asset_id"],
        },
    },
}


def _rect(v) -> list[float] | None:
    if not isinstance(v, list) or len(v) != 4:
        return None
    try:
        x, y, w, h = [float(t) for t in v]
    except Exception:
        return None
    x, y = max(0.0, min(0.95, x)), max(0.0, min(0.95, y))
    w, h = max(0.03, min(1.0 - x, w)), max(0.03, min(1.0 - y, h))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def _clean_ops(raw) -> list[dict]:
    out: list[dict] = []
    bg_seen = False
    for o in raw if isinstance(raw, list) else []:
        if not isinstance(o, dict):
            continue
        op = str(o.get("op") or "").strip()
        if op not in OPS:
            continue
        if op == "change_background":
            if bg_seen:
                continue
            bg_seen = True
            out.append({"op": op, "prompt": str(o.get("prompt") or "").strip()})
            continue
        role = str(o.get("role") or "").strip()
        if op != "add_text" and (not role or role in ("background", "design")):
            continue
        item: dict = {"op": op, "role": role}
        if op in ("change_text", "edit", "add_text") and o.get("content") is not None:
            item["content"] = str(o.get("content") or "")
            mode = str(o.get("mode") or "").strip().lower()
            if mode in ("verbatim", "generated"):
                item["mode"] = mode
        if op in ("change_color", "edit", "add_text") and o.get("color"):
            item["color"] = str(o.get("color") or "").strip()
        if op == "edit" and o.get("size_scale") is not None:
            try:
                item["size_scale"] = max(0.5, min(1.5, float(o.get("size_scale"))))
            except Exception:
                pass
        if op in ("change_asset", "add_asset", "edit"):
            aid = str(o.get("asset_id") or "").strip()
            if aid:
                item["asset_id"] = aid
            q = str(o.get("query") or "").strip()
            if q:
                item["query"] = q
        r = _rect(o.get("rect"))
        if r and op in ("reposition", "add_asset", "change_asset", "edit", "add_text"):
            item["rect"] = r
        if op in ("reposition", "add_text") and "rect" not in item:
            continue
        if op in ("change_text", "add_text") and not item.get("content"):
            continue
        if op == "change_color" and not item.get("color"):
            continue
        if op in ("change_asset", "add_asset") and not (item.get("query") or item.get("asset_id")):
            continue
        out.append(item)
    return out


def _heuristic_edit(instruction: str) -> dict:
    """Regex fallback when the thinking model is unreachable — keeps the edit
    workflow functional (and instant) for text / asset / background requests."""
    t = instruction.strip()
    low = t.lower()
    m = re.search(r"(headline|sub(?:head)?|body|cta)\b[^'\"’]*['\"’]([^'\"’]+)['\"’]", t, re.I)
    if m and re.search(r"\b(change|set|update|replace|rewrite|write|rename)\b", low):
        role = m.group(1).lower().replace("subhead", "sub")
        return {"ops": [{"op": "change_text", "role": role, "content": m.group(2), "mode": "verbatim"}]}
    if re.search(r"\b(remove|delete|drop|hide)\b", low):
        w = re.search(r"\b(?:remove|delete|drop|hide)\s+(?:the\s+|a\s+)?([\w-]+)", low)
        if w:
            return {"ops": [{"op": "remove", "role": w.group(1)}]}
    if re.search(r"\b(add|put|place|insert)\b", low):
        q = re.sub(r"^.*\b(?:add|put|place|insert)\s+(?:the\s+|a\s+)?", "", low).strip(" .!")
        q = re.split(r"\s+(?:on|in|at|to|near|beside|under|over|next)\b", q)[0].strip() or "accent"
        rect = [0.35, 0.35, 0.3, 0.3]
        if re.search(r"top[- ]?right", low):
            rect = [0.62, 0.05, 0.3, 0.3]
        elif re.search(r"top[- ]?left", low):
            rect = [0.05, 0.05, 0.3, 0.3]
        elif re.search(r"bottom[- ]?right", low):
            rect = [0.62, 0.6, 0.3, 0.3]
        elif re.search(r"bottom[- ]?left", low):
            rect = [0.05, 0.6, 0.3, 0.3]
        elif re.search(r"\bcenter|middle\b", low):
            rect = [0.3, 0.3, 0.4, 0.4]
        return {"ops": [{"op": "add_asset", "query": q, "role": "accent", "rect": rect}]}
    return {"ops": [{"op": "change_background", "prompt": t}]}


def classify_edit(instruction: str, manifest: dict, brand_id: str = "") -> dict:
    """User prompt → {"ops": [...]} typed layer instructions.

    The agent plans creatively (writes copy when the user gives intent), sees the
    full asset catalog in context, and can read_asset to VIEW candidates before
    choosing which one to place."""
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    zones = []
    for l in manifest.get("layers", []):
        if l.get("role") in ("background", "design") or l.get("visible") is False:
            continue
        x, y, w, h = [float(v) for v in (l.get("bbox") or [0, 0, 0, 0])]
        st = l.get("style") or {}
        zones.append(
            {
                "role": l.get("role"),
                "type": l.get("type"),
                "content": (l.get("content") or "")[:80],
                "bbox": [round(x / W, 2), round(y / H, 2), round(w / W, 2), round(h / H, 2)],
                "color": st.get("color") or st.get("fill") or "",
            }
        )
    try:
        from . import store

        catalog = store.load_catalog(brand_id) if brand_id else []
    except Exception:
        catalog = []
    payload = {
        "instruction": instruction,
        "layers": zones,
        "canvas": {"w": W, "h": H},
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "kind": a.kind,
                "description": (a.semantic or a.usage or "")[:140],
                "colors": list(a.colors or [])[:6],
            }
            for a in catalog
        ],
    }

    def dispatch(name: str, args: dict):
        if name == "read_asset":
            from . import store

            a = store.get_asset(brand_id, str(args.get("asset_id") or ""))
            if not a or not a.png:
                return f"no asset '{args.get('asset_id')}'"
            return [
                {"type": "text", "text": f"Asset {a.id} — {a.name} ({a.kind}): {(a.semantic or a.usage or '')[:120]}"},
                llm.img_part(a.png),
            ]
        return json.dumps({"error": f"unknown tool {name}"})

    try:
        raw = llm.chat_agent(
            EDIT_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            tools=[_READ_TOOL],
            dispatch=dispatch,
            model="pro",
        )
        data = _parse(raw)
        if not data:
            raise ValueError("empty classify response")
    except Exception:
        data = _heuristic_edit(instruction)
    return {"ops": _clean_ops(data.get("ops"))}


def kind_of(ops: list[dict]) -> str:
    kinds = set()
    for o in ops:
        op = o.get("op")
        if op in ("change_text", "add_text"):
            kinds.add("text")
        elif op == "reposition":
            kinds.add("layout")
        elif op in ("change_asset", "add_asset"):
            kinds.add("assets")
        elif op in ("change_color", "remove", "edit"):
            kinds.add("style")
        elif op == "change_background":
            kinds.add("background")
    if not kinds:
        return ""
    return kinds.pop() if len(kinds) == 1 else "both"


# ── manifest helpers ──────────────────────────────────────────────────────────


def load_manifest(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def save_manifest(path: str | Path, data: dict) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return str(p)


def design_path_of(manifest: dict) -> str:
    return manifest.get("design_src") or next(
        (l.get("src") for l in manifest.get("layers", []) if l.get("role") in ("design", "background")), ""
    )


def _layers(manifest: dict, role: str) -> list[dict]:
    return [
        l
        for l in manifest.get("layers", [])
        if l.get("role") == role and l.get("role") not in ("background", "design") and l.get("visible") is not False
    ]


def refit_text(manifest: dict) -> dict:
    """Re-fit every text layer's copy into its box (real metrics) and persist lines."""
    from .fidelity.render import bake_text_styles

    try:
        m = Manifest.model_validate(manifest)
    except Exception:
        return manifest
    bake_text_styles(m)
    return m.model_dump()


def preview_of(manifest: dict, design_src: str, out_path: Path) -> str:
    """Flatten bg + layers into a preview composite (gallery/thumbnail)."""
    from .fidelity.render import bake_text_styles, render_composite

    try:
        m = Manifest.model_validate(manifest)
    except Exception:
        return design_src
    bake_text_styles(m)
    return render_composite(design_src or design_path_of(manifest), m, str(out_path))


# ── layer appliers (deterministic — the ops only mutate the manifest) ─────────


def apply_text_changes(manifest: dict, changes: list[dict]) -> dict:
    by_role = {c.get("role"): c.get("content", "") for c in changes}
    for l in manifest.get("layers", []):
        if l.get("type") == "text" and l.get("role") in by_role:
            l["content"] = by_role[l["role"]]
            # re-fit happens on render — drop stale pre-baked lines
            if isinstance(l.get("style"), dict):
                l["style"].pop("lines", None)
    return manifest


def apply_move_changes(manifest: dict, moves: list[dict]) -> dict:
    """Reposition/rescale existing layers (layout edits).

    A shape whose role pairs with the moved role (cta_pill ↔ cta) rides along
    with the same delta — the pill never splits from its label."""
    by_role = {m.get("role"): m.get("rect") for m in moves}
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    layers = manifest.get("layers", [])
    deltas: dict[str, tuple[float, float]] = {}
    for l in layers:
        role = l.get("role")
        r = by_role.get(role)
        if not r or role in ("design", "background"):
            continue
        x, y, w, h = [float(v) for v in r]
        old = [float(v) for v in (l.get("bbox") or [0.0, 0.0, 0.0, 0.0])]
        new = [x * W, y * H, max(8.0, w * W), max(8.0, h * H)]
        deltas[role] = (new[0] - old[0], new[1] - old[1])
        l["bbox"] = new
        if isinstance(l.get("style"), dict):
            l["style"].pop("lines", None)  # re-fit to the new box
    for l in layers:
        role = l.get("role")
        if not role or role in deltas or role in ("design", "background"):
            continue
        for mrole, (dx, dy) in deltas.items():
            if role in (f"{mrole}_pill", f"{mrole}_bg") or mrole in (f"{role}_pill", f"{role}_label"):
                old = [float(v) for v in (l.get("bbox") or [0.0, 0.0, 0.0, 0.0])]
                l["bbox"] = [old[0] + dx, old[1] + dy, old[2], old[3]]
                if isinstance(l.get("style"), dict):
                    l["style"].pop("lines", None)
                break
    return manifest


def _apply_color(manifest: dict, role: str, color: str) -> str:
    hit = 0
    for l in _layers(manifest, role):
        st = dict(l.get("style") or {})
        if l.get("type") == "text":
            st["color"] = color
        elif l.get("type") == "shape":
            st["fill"] = color
        else:
            continue  # image colourways are baked into the PNG — swap asset instead
        l["style"] = st
        hit += 1
    return f"color: {role} → {color}" if hit else f"color: no recolourable layer '{role}'"


def _apply_remove(manifest: dict, role: str) -> str:
    before = len(manifest.get("layers", []))
    manifest["layers"] = [l for l in manifest.get("layers", []) if l.get("role") != role or l.get("role") in ("background", "design")]
    n = before - len(manifest["layers"])
    return f"remove: {role} ({n} layer{'s' if n != 1 else ''})" if n else f"remove: no layer '{role}'"


def rag_assets(brand_id: str, query: str, k: int = 3) -> list:
    """RAG over the indexed catalog — see app.rag.retrieve."""
    from .rag import retrieve

    return retrieve(brand_id, query, k=k)


def _asset_layer_fields(asset) -> dict:
    return {"src": asset.png, "asset_id": asset.id, "style_field": {"colorway": getattr(asset, "colorway", "")}}


def _resolve_asset(brand_id: str, op: dict):
    """asset_id (picked via the search_assets tool) wins; query = fallback RAG."""
    from . import store

    aid = str(op.get("asset_id") or "").strip()
    if aid:
        a = store.get_asset(brand_id, aid)
        if a and a.png:
            return a
    query = op.get("query") or op.get("role") or ""
    return (rag_assets(brand_id, query, k=1) or rag_assets(brand_id, op.get("role") or "", k=1) or [None])[0]


def _apply_swap_asset(manifest: dict, role: str, op: dict, brand_id: str) -> str:
    targets = [l for l in _layers(manifest, role) if l.get("type") == "image"]
    if not targets:
        return f"asset: no image layer '{role}' to swap"
    a = _resolve_asset(brand_id, op)
    if not a:
        return f"asset: no catalog match for '{op.get('query') or op.get('asset_id') or role}'"
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    rect = op.get("rect")
    for l in targets:
        l["src"] = a.png
        l["asset_id"] = a.id
        st = dict(l.get("style") or {})
        st["colorway"] = getattr(a, "colorway", "")
        st["placed_by"] = "rag"
        st["why"] = f"RAG: '{op.get('query') or op.get('asset_id') or role}' → {a.name}"
        l["style"] = st
        if rect:
            x, y, w, h = rect
            l["bbox"] = [x * W, y * H, max(8.0, w * W), max(8.0, h * H)]
    return f"asset: {role} → {a.name}"


def _apply_add_asset(manifest: dict, op: dict, brand_id: str) -> str:
    role = op.get("role") or "accent"
    a = _resolve_asset(brand_id, op)
    if not a:
        return f"add: no catalog match for '{op.get('query') or op.get('asset_id')}'"
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    x, y, w, h = op.get("rect") or [0.35, 0.35, 0.3, 0.3]
    manifest["layers"] = list(manifest.get("layers", [])) + [
        {
            "type": "image",
            "role": role,
            "src": a.png,
            "asset_id": a.id,
            "bbox": [x * W, y * H, max(8.0, w * W), max(8.0, h * H)],
            "style": {"placed_by": "rag", "why": f"RAG: '{op.get('query') or op.get('asset_id')}' → {a.name}", "colorway": getattr(a, "colorway", "")},
            "locked": False,
            "baked": False,
            "visible": True,
        }
    ]
    return f"add: '{op.get('query') or op.get('asset_id')}' → {a.name} @ {[round(v, 2) for v in (op.get('rect') or [])]}"


def _apply_add_text(manifest: dict, op: dict) -> str:
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    x, y, w, h = op.get("rect") or [0.1, 0.7, 0.5, 0.15]
    content = str(op.get("content") or "")
    mode = op.get("mode") or "generated"
    manifest["layers"] = list(manifest.get("layers", [])) + [
        {
            "type": "text",
            "role": op.get("role") or "note",
            "content": content,
            "bbox": [x * W, y * H, max(8.0, w * W), max(8.0, h * H)],
            "style": {
                "font": "Figtree",
                "fallback": "system-ui, sans-serif",
                "color": op.get("color") or "#000856",
                "align": "left",
                "weight": 400,
                "padding": 0,
                "draw_bg": False,
                "placed_by": "agent",
                "mode": mode,
            },
            "locked": False,
            "baked": False,
            "visible": True,
        }
    ]
    return f"add text: {op.get('role')} '{content[:24]}' ({mode}) @ {[round(v, 2) for v in (op.get('rect') or [])]}"


def _apply_edit(manifest: dict, op: dict, brand_id: str) -> list[str]:
    """Generic partial restyle — dispatches each provided field by layer type."""
    role = op.get("role") or ""
    notes = []
    if op.get("content") is not None:
        apply_text_changes(manifest, [{"role": role, "content": op.get("content")}])
        notes.append(f"edit text: {role} → '{str(op.get('content'))[:24]}'")
    if op.get("color"):
        notes.append(_apply_color(manifest, role, op["color"]))
    if op.get("rect"):
        apply_move_changes(manifest, [{"role": role, "rect": op["rect"]}])
        notes.append(f"edit box: {role} → {[round(v, 2) for v in op['rect']]}")
    if op.get("size_scale"):
        for l in _layers(manifest, role):
            if l.get("type") != "text":
                continue
            st = dict(l.get("style") or {})
            st["size_scale"] = max(0.5, min(1.5, float(st.get("size_scale") or 1.0) * float(op["size_scale"])))
            st.pop("lines", None)
            l["style"] = st
        notes.append(f"edit size: {role} ×{op['size_scale']}")
    if op.get("query") or op.get("asset_id"):
        notes.append(_apply_swap_asset(manifest, role, op, brand_id))
    return notes or [f"edit: nothing applicable on '{role}'"]


def apply_ops(manifest: dict, ops: list[dict], brand_id: str = "") -> tuple[dict, list[str], dict | None]:
    """Apply layer ops in order. change_background is deferred and returned.

    Returns (manifest, notes, bg_op)."""
    notes: list[str] = []
    bg_op: dict | None = None
    for op in ops:
        name = op.get("op")
        if name == "change_background":
            bg_op = op
            continue
        if name == "change_text":
            apply_text_changes(manifest, [{"role": op.get("role"), "content": op.get("content", "")}])
            notes.append(f"text: {op.get('role')}→'{str(op.get('content'))[:24]}' ({op.get('mode') or 'verbatim'})")
        elif name == "add_text":
            notes.append(_apply_add_text(manifest, op))
        elif name == "change_color":
            notes.append(_apply_color(manifest, op.get("role") or "", op.get("color") or ""))
        elif name == "reposition":
            apply_move_changes(manifest, [{"role": op.get("role"), "rect": op.get("rect")}])
            notes.append(f"moved: {op.get('role')} → {[round(v, 2) for v in (op.get('rect') or [])]}")
        elif name == "remove":
            notes.append(_apply_remove(manifest, op.get("role") or ""))
        elif name == "change_asset":
            notes.append(_apply_swap_asset(manifest, op.get("role") or "", op, brand_id))
        elif name == "add_asset":
            notes.append(_apply_add_asset(manifest, op, brand_id))
        elif name == "edit":
            notes.extend(_apply_edit(manifest, op, brand_id))
    return manifest, notes, bg_op


# ── readability judgement (the wireframe must READ) ───────────────────────────


def _lum(c: str) -> float:
    s = (c or "").lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return 128.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _cr(a: str, b: str) -> float:
    """WCAG-style contrast ratio between two hex colours."""
    la, lb = _lum(a) / 255.0, _lum(b) / 255.0
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _readable_ink(bg: str) -> str:
    return "#FFFFFF" if _lum(bg) < 140 else "#000856"


def _rects_overlap(a, b) -> bool:
    try:
        ax, ay, aw, ah = [float(v) for v in a]
        bx, by, bw, bh = [float(v) for v in b]
    except Exception:
        return False
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _container_fill(role: str, fills: dict[str, str]) -> str | None:
    """The shape a label rides on: cta → cta_pill / cta_bg, x_label → x."""
    for cand in (f"{role}_pill", f"{role}_bg"):
        if fills.get(cand):
            return fills[cand]
    if role.endswith("_label") and fills.get(role[: -len("_label")]):
        return fills[role[: -len("_label")]]
    return None


def judge_wireframe(brief) -> list[str]:
    """Deterministic readability judgement of the wireframe (before fill).

    Flags pieces that won't read and remedies them:
    - label vs its container shape → change of TEXT colour
    - text vs the colour field it sits on → change of BACKGROUND (the field)"""
    from .brief.placements import _intent_hex

    notes: list[str] = []
    shapes = {p.role: (p.style or {}).get("fill") or "" for p in (brief.placements or []) if p.kind == "shape"}
    for p in brief.placements or []:
        if p.kind != "text" or not (p.content or "").strip():
            continue
        st = dict(p.style or {})
        ink = st.get("color") or "#000856"
        cont = _container_fill(p.role, shapes)
        if cont and _cr(ink, cont) < 3.0:
            new = _readable_ink(cont)
            st["color"] = new
            p.style = st
            notes.append(f"⚠ contrast: {p.role} ink {ink} on {cont} → text set {new}")
            ink = new
        for f in brief.bg_fields or []:
            if not _rects_overlap(p.rect, f.rect):
                continue
            fcol = f.color or _intent_hex(f.intent, "")
            if fcol and _cr(ink, fcol) < 3.0:
                newf = _field_hex(ink)
                f.color = newf
                notes.append(f"⚠ contrast: {p.role} ink {ink} on field {fcol} → background field set {newf}")
    return notes


def judge_wireframe_layers(manifest: dict) -> tuple[dict, list[str]]:
    """Same judgement over manifest layers (edit flow) — container clashes only;
    the fields are derived from the inks at prompt time, so ink fixes keep them
    consistent."""
    notes: list[str] = []
    shapes = {l.get("role"): (l.get("style") or {}).get("fill") or "" for l in manifest.get("layers", []) if l.get("type") == "shape"}
    for l in manifest.get("layers", []):
        if l.get("type") != "text" or l.get("role") in ("background", "design") or not (l.get("content") or "").strip():
            continue
        st = dict(l.get("style") or {})
        ink = st.get("color") or "#000856"
        cont = _container_fill(l.get("role") or "", shapes)
        if cont and _cr(ink, cont) < 3.0:
            new = _readable_ink(cont)
            st["color"] = new
            st.pop("lines", None)
            l["style"] = st
            notes.append(f"⚠ contrast: {l.get('role')} ink {ink} on {cont} → text set {new}")
    return manifest, notes


READABILITY_SYSTEM = """You review a layered ad composite for READABILITY of each pasted piece against what sits behind it (the page background or its container shape).
Report ONLY pieces that are hard to read: low contrast, clashing colour, lost in the background artwork.
Reply ONLY JSON:
{"flags": [{"role": str, "target": "text"|"container"|"background", "color": "#RRGGBB", "bg_tone": "light"|"dark", "issue": str}]}
- target="text" → the text ink should become color
- target="container" → the shape/pill behind the label should become color
- target="background" → the background area behind the piece should become color
- bg_tone = the tone of the area DIRECTLY behind the piece ("dark" backdrop → pick a LIGHT ink; "light" backdrop → pick a DARK ink)
Choose the smallest remedy that makes the piece read. Empty list if everything reads well."""


def _tone_ink(tone: str, palette: list[str] | None) -> str:
    """Palette ink of the readable tone for a backdrop (fallback ivory/ink)."""
    want_light = tone == "dark"
    for h in palette or []:
        if h and (_lum(h) >= 140) == want_light:
            return h
    return "#FFFFFF" if want_light else "#111111"


def judge_readability(png: str, manifest: dict, allow_bg: bool = True, palette: list[str] | None = None) -> list[dict]:
    """Vision judgement on the composite — what the eye actually sees.

    allow_bg=False (generation flow, no second fill): remedies are limited to
    text/container recolours — never a background repaint target.
    palette: preferred brand hexes so remedies stay colour-coordinated."""
    sys_txt = READABILITY_SYSTEM
    if not allow_bg:
        sys_txt += """
CONSTRAINT: the background CANNOT be repainted — NEVER use target "background". Recolour the TEXT ink or its CONTAINER instead."""
    if palette:
        sys_txt += f"""
Keep the design COLOUR-COORDINATED: prefer remedies from the brand palette {", ".join(palette[:8])} (e.g. a cream/ivory ink over dark areas, a deep brand ink over light areas) before generic black/grey."""
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    pieces = []
    for l in manifest.get("layers", []):
        if l.get("role") in ("background", "design") or l.get("visible") is False:
            continue
        st = l.get("style") or {}
        x, y, w, h = [float(v) for v in (l.get("bbox") or [0, 0, 0, 0])]
        pieces.append(
            {
                "role": l.get("role"),
                "type": l.get("type"),
                "content": (l.get("content") or "")[:60],
                "ink": st.get("color") or "",
                "fill": st.get("fill") or "",
                "bbox": [round(x / W, 2), round(y / H, 2), round(w / W, 2), round(h / H, 2)],
            }
        )
    try:
        raw = llm.chat_vision(
            sys_txt,
            [
                {"type": "text", "text": f"Canvas {int(W)}x{int(H)}. Pieces:\n{json.dumps(pieces, ensure_ascii=False)}"},
                llm.img_part(png, detail="high"),
            ],
            model="kimi-latest",
            json_mode=True,
            timeout=90.0,
            attempts=2,
        )
    except Exception:
        return []
    data = _parse(raw)
    flags = []
    for f in data.get("flags", []) if isinstance(data, dict) else []:
        if not isinstance(f, dict) or not f.get("role"):
            continue
        target = str(f.get("target") or "text")
        if target not in ("text", "container", "background") or (not allow_bg and target == "background"):
            target = "text"
        color = str(f.get("color") or "").strip()
        if not re.match(r"^#[0-9a-fA-F]{3,8}$", color):
            continue
        if target == "text":
            # deterministic tone guard: a vision misread must not put white on
            # cream or navy on night — reconcile against the declared backdrop
            tone = str(f.get("bg_tone") or "").lower()
            if tone in ("light", "dark"):
                lum = _lum(color)
                if (tone == "dark") != (lum >= 140):
                    color = _tone_ink(tone, palette)
        flags.append({"role": str(f["role"]), "target": target, "color": color, "issue": str(f.get("issue") or "")[:120]})
    return flags


def apply_readability(manifest: dict, flags: list[dict]) -> tuple[dict, list[str], dict[str, str]]:
    """Remedy flags: text / container recolours here; background targets become
    field overrides for a repaint. Returns (manifest, notes, bg_overrides)."""
    notes: list[str] = []
    overrides: dict[str, str] = {}
    shapes = {l.get("role"): l for l in manifest.get("layers", []) if l.get("type") == "shape"}
    for f in flags:
        role, target, color = f.get("role") or "", f.get("target") or "text", f.get("color") or ""
        issue = f.get("issue") or ""
        if target == "text":
            notes.append(_apply_color(manifest, role, color) + (f" — {issue}" if issue else ""))
        elif target == "container":
            hit = 0
            for cand in (f"{role}_pill", f"{role}_bg", role):
                l = shapes.get(cand)
                if l:
                    st = dict(l.get("style") or {})
                    fill = str(st.get("fill") or "").strip().lower()
                    if fill in ("", "none", "null", "transparent"):
                        st["stroke"] = color  # hollow ring/frame — recolour the stroke, keep it hollow
                    else:
                        st["fill"] = color
                    l["style"] = st
                    hit += 1
            notes.append((f"container: {role} → {color}" if hit else f"container: no shape behind '{role}'") + (f" — {issue}" if issue else ""))
        else:  # background — repaint with a forced field colour
            overrides[role] = color
            notes.append(f"background: field under {role} → {color}" + (f" — {issue}" if issue else ""))
    return manifest, notes, overrides


# ── background re-prompt (same lines as generation) ───────────────────────────


def _field_hex(ink: str) -> str:
    """Flat field colour that makes a piece of this ink read (no pixel analysis)."""
    s = (ink or "").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return "#FFF8E7"
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000856" if lum > 140 else "#FFF8E7"


def wire_from_manifest(manifest: dict, out_path: Path | str) -> str:
    """Render every visible foreground layer at its final position over transparency."""
    from .layout.canvas import render_proof_from_manifest

    return render_proof_from_manifest(manifest, out_path)


def bg_prompt_edit(manifest: dict, intent: str, grammar=None, field_overrides: dict[str, str] | None = None) -> str:
    """Describe the background around every visible item in the updated layout."""
    canvas = manifest.get("canvas") or {"w": 1024, "h": 1024}
    W, H = float(canvas.get("w") or 1024), float(canvas.get("h") or 1024)
    lines = [
        "The attached transparent PNG is the exact updated foreground layout. Every visible text layer, "
        "brand asset, and shape is rendered at its final position, size, rotation, and colour. Treat "
        "the mapped pixels and coordinates as authoritative.",
        f"Paint only a full-bleed background scene coordinated with this layout: {intent or 'artwork that matches the existing design mood'}.",
        "Do not move, resize, recolour, redraw, remove, or cover any mapped item. The foreground will be "
        "composited over the generated background by code. Keep the background visually calm behind text; "
        "do not add panels, cards, borders, or other foreground objects.",
    ]
    i = 0
    for l in manifest.get("layers", []):
        if l.get("type") == "raster" or l.get("role") in ("background", "design") or l.get("visible") is False:
            continue
        st = l.get("style") or {}
        if l.get("type") == "text":
            ink = st.get("color") or "#000856"
            description = f"text {l.get('role')!r} ({(l.get('content') or '')!r}), ink {ink}"
        elif l.get("type") == "shape":
            ink = ""
            description = f"{st.get('shape') or 'rect'} shape {l.get('role')!r}, fill {st.get('fill') or 'transparent'}"
        elif l.get("type") == "image":
            ink = ""
            description = f"brand asset {l.get('role')!r}"
        else:
            continue
        x, y, w, h = [float(v) for v in (l.get("bbox") or [0, 0, 0, 0])]
        x, y, w, h = round(x / W, 2), round(y / H, 2), round(w / W, 2), round(h / H, 2)
        i += 1
        lines.append(f"- mapped item {i}: {description} at x={x} y={y} w={w} h={h}.")
        if l.get("type") == "text":
            col = (field_overrides or {}).get(l.get("role")) or _field_hex(ink)
            lines.append(f"  Keep this text area low-detail and coordinate the background toward {col}.")
    if grammar and getattr(grammar, "palette", None):
        pal = ", ".join(f"{p.get('name', '')} {p.get('hex', '')}".strip() for p in grammar.palette[:8])
        lines.append(f"Brand palette only: {pal}.")
    lines.append("Do not generate any text, logos, watermarks, UI, panels, cards, or borders. Generate only the background scene, edge to edge.")
    lines.append(_BG_FORBID)
    return "\n".join(lines)


def repaint_background(
    manifest: dict,
    intent: str,
    out_path: Path | str,
    brand_id: str = "",
    workdir: Path | None = None,
    field_overrides: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Same lines as generation: updated layers → wireframe (reference) → the model
    paints the whole background → pieces stay live on top.

    Returns (bg_path, fill_prompt, wireframe_path)."""
    out = Path(out_path)
    workdir = Path(workdir) if workdir else out.parent
    workdir.mkdir(parents=True, exist_ok=True)
    wire = workdir / "ref_wire.png"
    wire_from_manifest(manifest, wire)
    grammar = None
    try:
        from . import store

        grammar = store.load_grammar(brand_id) if brand_id else None
    except Exception:
        pass
    prompt = bg_prompt_edit(manifest, intent, grammar, field_overrides=field_overrides)
    ratio = manifest.get("ratio") or "1:1"
    size = {"1:1": "1024x1024", "4:5": "1024x1280", "9:16": "1024x1536", "16:9": "1536x1024"}.get(ratio, "1024x1024")
    raw = llm.edit_image(prompt, wire, size=size, strength=0.8)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    # swap the background raster — every other layer is untouched
    manifest["design_src"] = str(out)
    for l in manifest.get("layers", []):
        if l.get("role") in ("design", "background"):
            l["src"] = str(out)
    return str(out), prompt, str(wire)
