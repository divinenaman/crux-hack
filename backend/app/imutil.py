import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from . import config

RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _looks_raster(path: Path) -> bool:
    if path.suffix.lower() not in RASTER_EXTS:
        return False
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def _rasterize_svg(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import cairosvg

        png = cairosvg.svg2png(url=str(src), output_width=1024)
        out.write_bytes(png)
        return
    except Exception:
        pass
    ql = shutil.which("qlmanage")
    if ql:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([ql, "-t", "-s", "1024", "-o", td, str(src)], check=True, capture_output=True)
            produced = list(Path(td).glob("*.png"))
            if produced:
                shutil.copy(produced[0], out)
                return
    raise RuntimeError(f"no SVG rasterizer available for {src}")


def ensure_raster(path: str | Path, out: str | Path | None = None) -> str:
    """Return a path to a PNG/JPEG/WEBP file; rasterize SVGs (and other
    non-decodable files) into the assets dir. Raises on failure."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if _looks_raster(p):
        return str(p)
    dest = Path(out) if out else config.ASSETS_DIR / f"{p.stem}_raster.png"
    if dest.suffix.lower() not in RASTER_EXTS:
        dest = dest.with_suffix(".png")
    if dest.exists() and _looks_raster(dest) and dest.stat().st_mtime >= p.stat().st_mtime:
        return str(dest)
    _rasterize_svg(p, dest)
    return str(dest)
