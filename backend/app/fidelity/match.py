import numpy as np
from PIL import Image

from ..imutil import ensure_raster


def _load_rgba(path: str) -> Image.Image:
    return Image.open(ensure_raster(path)).convert("RGBA")


def _on_white(im: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.paste(im, (0, 0), im)
    return bg.convert("RGB")


def _gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"), dtype=np.float32)


def find_assets(brand_id: str, image_path: str, asset_ids: list[str], scales: tuple[float, ...] = (0.15, 0.25, 0.35, 0.5, 0.7, 1.0)) -> dict[str, dict]:
    canvas = _gray(_on_white(_load_rgba(image_path)))
    ch, cw = canvas.shape
    out: dict[str, dict] = {}

    from .. import store

    for aid in asset_ids:
        asset = store.get_asset(brand_id, aid)
        if not asset or not asset.png:
            continue
        try:
            tpl0 = _on_white(_load_rgba(asset.png))
        except Exception:
            continue

        best = {"score": -1.0, "bbox": None}
        fit = min(cw / tpl0.width, ch / tpl0.height) * 0.9
        scale_set = sorted(set(scales) | {round(fit * s, 3) for s in (0.12, 0.2, 0.35, 0.6)})
        for s in scale_set:
            tw, th = max(8, int(tpl0.width * s)), max(8, int(tpl0.height * s))
            if tw >= cw or th >= ch:
                continue
            tpl = np.asarray(tpl0.resize((tw, th)).convert("L"), dtype=np.float32)
            t = tpl - tpl.mean()
            denom_t = np.sqrt((t * t).sum()) + 1e-6
            for y in range(0, ch - th, max(4, th // 4)):
                for x in range(0, cw - tw, max(4, tw // 4)):
                    win = canvas[y : y + th, x : x + tw]
                    w = win - win.mean()
                    score = float((w * t).sum() / (denom_t * (np.sqrt((w * w).sum()) + 1e-6)))
                    if score > best["score"]:
                        best = {"score": score, "bbox": [x, y, tw, th], "scale": s}
        out[aid] = _refine(canvas, tpl0, best)

    return out


def _refine(canvas: np.ndarray, tpl0: Image.Image, best: dict) -> dict:
    if not best.get("bbox"):
        return best
    x0, y0, tw, th = [int(v) for v in best["bbox"]]
    tpl = np.asarray(tpl0.resize((tw, th)).convert("L"), dtype=np.float32)
    t = tpl - tpl.mean()
    denom_t = np.sqrt((t * t).sum()) + 1e-6
    ch, cw = canvas.shape
    for y in range(max(0, y0 - 3), min(ch - th, y0 + 4)):
        for x in range(max(0, x0 - 3), min(cw - tw, x0 + 4)):
            win = canvas[y : y + th, x : x + tw]
            w = win - win.mean()
            score = float((w * t).sum() / (denom_t * (np.sqrt((w * w).sum()) + 1e-6)))
            if score > best["score"]:
                best["score"] = score
                best["bbox"] = [x, y, tw, th]
    return best


def paste_exact(brand_id: str, image_path: str, asset_id: str, bbox: list[float], out_path: str) -> str:
    from .. import store

    asset = store.get_asset(brand_id, asset_id)
    if not asset or not asset.png:
        return image_path
    canvas = Image.open(image_path).convert("RGBA")
    el = _load_rgba(asset.png)
    x, y, w, h = [int(v) for v in bbox]
    if w <= 0 or h <= 0:
        return image_path
    el = el.resize((w, h))
    canvas.paste(el, (x, y), el)
    canvas.convert("RGB").save(out_path)
    return out_path
