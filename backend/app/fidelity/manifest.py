"""Layered manifest builder — layout-first.

The manifest is separation by construction:
  layer 0  raster  — the generated background (hole-filled, colour-controlled)
  layers…  shape   — designed geometry (pills, cards, bands)
  layers…  image   — exact brand element PNGs (colourway-coordinated)
  layers…  text    — exact copy in the brand font, font colour only (no box)

Nothing was ever baked into one raster and stripped back out — the pieces were
placed on the canvas, the fill painted around them, and the layers ARE those
pieces. Bboxes are px [x,y,w,h]; text style carries pre-fitted size/lines so
Konva renders what the layout proof judged.
"""
from __future__ import annotations

from pathlib import Path

from .. import store
from ..fidelity.typo import fit_text_block
from ..layout.canvas import asset_paste_box, canvas_size
from ..models import Brief, Layer, Manifest, Placement

Z_ORDER = {"shape": 0, "image": 1, "text": 2}


def _font_style(p: Placement, W: int, H: int) -> dict:
    st = dict(p.style or {})
    font = str(st.get("font") or st.get("font_family") or "")
    fp = None
    from ..fidelity.typo import resolve_font_path

    src = str(st.get("font_src") or "")
    if src.startswith("/files/fonts/"):
        from .. import config

        cand = config.WORKSPACE / "fonts" / src.split("/")[-1]
        if cand.exists():
            fp = str(cand)
    if not fp:
        fp = resolve_font_path(font)
    out = {
        "font": font or (Path(fp).stem if fp else "Figtree"),
        "fallback": st.get("fallback", "system-ui, sans-serif"),
        "color": st.get("color", "#000856"),
        "align": st.get("align", "left"),
        "weight": int(st.get("weight") or 400),
        "padding": int(st.get("padding") or 0),
        "draw_bg": False,  # policy: text never sits in a box — font colour only
        "placed_by": "layout",
    }
    if fp:
        out["font_src"] = "/files/fonts/" + Path(fp).name
        out["font_path"] = fp
    w_px = max(40.0, p.rect[2] * W)
    h_px = max(16.0, p.rect[3] * H)
    fit = fit_text_block(fp, p.content, w_px, h_px, weight=out["weight"], line_gap=float(st.get("lineHeight") or 1.15))
    if st.get("size"):
        fit = fit_text_block(fp, p.content, w_px, h_px, weight=out["weight"], force_size=int(st["size"]))
    out["size"] = fit["size"]
    out["lines"] = fit["lines"]
    out["lineGap"] = fit["line_gap"]
    out["lineHeight"] = fit["line_gap"]
    return out


def build_manifest(brand_id: str, job_id: str, variant_id: str, bg_path: str, brief: Brief) -> Manifest:
    W, H = canvas_size(getattr(brief, "ratio", "1:1"))
    catalog = {a.id: a for a in store.load_catalog(brand_id)} if brand_id else {}
    layers: list[Layer] = [
        Layer(type="raster", role="background", src=bg_path, locked=False, bbox=[0, 0, float(W), float(H)], style={"placed_by": "fill"})
    ]
    ordered = sorted(brief.placements or [], key=lambda p: Z_ORDER.get(p.kind, 1))
    for p in ordered:
        x, y, w, h = [float(v) for v in p.rect]
        bbox = [x * W, y * H, w * W, h * H]
        st = dict(p.style or {})
        if p.kind == "shape":
            layers.append(
                Layer(
                    type="shape",
                    role=p.role,
                    bbox=bbox,
                    style={
                        "shape": str(st.get("shape") or "rect"),
                        "fill": st.get("fill", "#0b1a3a"),
                        "stroke": st.get("stroke", ""),
                        "strokeWidth": int(st.get("strokeWidth") or 0),
                        "radius": float(st.get("radius") or 0),
                        "rotation": float(st.get("rotation") or 0),
                        "placed_by": "layout",
                    },
                    locked=False,
                )
            )
        elif p.kind == "image":
            a = catalog.get(p.asset_id)
            if not a or not a.png:
                continue
            paste = asset_paste_box(p, a.png, W, H)
            layers.append(
                Layer(
                    type="image",
                    role=p.role,
                    src=a.png,
                    asset_id=a.id,
                    bbox=paste,
                    style={"fit": st.get("fit", "contain"), "colorway": a.colorway, "rotation": float(st.get("rotation") or 0), "placed_by": "layout"},
                    locked=False,
                )
            )
        elif p.kind == "text":
            layers.append(
                Layer(
                    type="text",
                    role=p.role,
                    content=p.content,
                    bbox=bbox,
                    style=_font_style(p, W, H),
                    locked=False,
                )
            )
    return Manifest(
        job_id=job_id,
        variant_id=variant_id,
        canvas={"w": float(W), "h": float(H)},
        ratio=getattr(brief, "ratio", "1:1"),
        layers=layers,
        design_src=bg_path,
        pending_layers=False,
    )
