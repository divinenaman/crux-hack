import numpy as np
from PIL import Image


def _to_gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"), dtype=np.float32)


def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    runs = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    if start is not None and len(mask) - start >= min_len:
        runs.append((start, len(mask)))
    return runs


def detect_grid_cells(path, min_cell: int = 80, gutter_ratio: float = 0.012) -> list[tuple[int, int, int, int]]:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    gray = _to_gray(im)
    gut = max(3, int(min(w, h) * gutter_ratio))
    thr = 245.0

    col_white = (gray > thr).mean(axis=0) > 0.97
    row_white = (gray > thr).mean(axis=1) > 0.97

    col_gaps = _runs(col_white, gut)
    row_gaps = _runs(row_white, gut)

    def bounds(gaps: int, size: int) -> list[tuple[int, int]]:
        edges = [0] + [g for pair in gaps for g in pair] + [size]
        cells = []
        for i in range(0, len(edges) - 1, 2):
            a, b = edges[i], edges[i + 1]
            if b - a >= min_cell:
                cells.append((a, b))
        return cells

    cols = bounds(col_gaps, w)
    rows = bounds(row_gaps, h)
    cells = []
    for y0, y1 in rows:
        for x0, x1 in cols:
            if (x1 - x0) >= min_cell and (y1 - y0) >= min_cell:
                crop = gray[y0:y1, x0:x1]
                if crop.std() > 4:
                    cells.append((x0, y0, x1, y1))
    return cells


def crop_cells(path, out_dir, prefix: str) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    im = Image.open(path).convert("RGBA")
    cells = detect_grid_cells(path)
    out = []
    for i, (x0, y0, x1, y1) in enumerate(cells):
        pad = 2
        box = (max(0, x0 + pad), max(0, y0 + pad), min(im.width, x1 - pad), min(im.height, y1 - pad))
        cell = im.crop(box)
        bbox = cell.getbbox()
        if bbox:
            cell = cell.crop(bbox)
        name = f"{prefix}_cell{i:02d}"
        p = out_dir / f"{name}.png"
        cell.save(p)
        out.append({"name": name, "png": str(p), "bbox": [float(box[0]), float(box[1]), float(box[2]), float(box[3])]})
    return out


def trim_to_content(path, out_path=None) -> str:
    im = Image.open(path).convert("RGBA")
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    out = out_path or path
    im.save(out)
    return str(out)
