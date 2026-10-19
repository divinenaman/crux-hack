from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, store
from ..imutil import ensure_raster
from ..models import Brief


def build_contact_sheet(brand_id: str, brief: Brief, out_path: Path, cols: int = 4, cell: int = 360) -> str:
    # show every distinct selected asset (capped at 8 cells) — independent of
    # MAX_ASSET_REFS which only limits raw refs attached to the image API call
    seen: set[str] = set()
    fills = []
    for f in brief.slots:
        if f.asset_id in seen:
            continue
        seen.add(f.asset_id)
        fills.append(f)
    fills = fills[:8]
    if not fills:
        out_path.write_bytes(b"")
        return str(out_path)

    rows = (len(fills) + cols - 1) // cols
    label_h = 56
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    for i, fill in enumerate(fills):
        asset = store.get_asset(brand_id, fill.asset_id)
        if not asset or not asset.png or not Path(asset.png).exists():
            continue
        try:
            im = Image.open(ensure_raster(asset.png)).convert("RGBA")
        except Exception:
            continue
        im.thumbnail((cell - 24, cell - 24))
        bg = Image.new("RGBA", (cell, cell), (255, 255, 255, 255))
        bg.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2), im)
        x = (i % cols) * cell
        y = (i // cols) * (cell + label_h)
        sheet.paste(bg.convert("RGB"), (x, y))
        draw.rectangle([x + 2, y + 2, x + cell - 2, y + cell - 2], outline=(200, 200, 200))
        draw.text((x + 10, y + cell + 10), f"{i + 1}. {asset.name[:28]}", fill=(0, 0, 0))
        draw.text((x + 10, y + cell + 30), f"role: {fill.role}", fill=(80, 80, 80))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return str(out_path)
