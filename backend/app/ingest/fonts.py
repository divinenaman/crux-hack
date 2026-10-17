"""Font identification during brand-kit ingestion.

Runs as a pipeline step: reads guideline/typography pages through the vision
model, records headline/body fonts into grammar.typography, and resolves the
named fonts to usable font files (workspace/fonts/, system, known open families).
"""
import re
from pathlib import Path

from .. import config, llm

FONT_SYSTEM = """You identify brand typography from brand-guideline pages.
Reply ONLY JSON:
{"headline_font": str, "body_font": str, "weights": [str], "notes": str, "confidence": 0..1}
Rules:
- headline_font / body_font = the exact family name shown on the page (e.g. "Xero Sans", "Figtree").
- Empty strings if the page shows no typography info.
- notes = one short line on weights/usage (e.g. "Bold for headlines, Regular for body")."""

# known open families we can fetch from Google Fonts when missing locally
_OPEN_FAMILIES = {
    "figtree": "https://raw.githubusercontent.com/google/fonts/main/ofl/figtree/Figtree%5Bwght%5D.ttf",
    "inter": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
    "roboto": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth,wght%5D.ttf",
    "open sans": "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans%5Bwdth,wght%5D.ttf",
    "lato": "https://raw.githubusercontent.com/google/fonts/main/ofl/lato/Lato-Regular.ttf",
    "montserrat": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "poppins": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Regular.ttf",
    "nunito": "https://raw.githubusercontent.com/google/fonts/main/ofl/nunito/Nunito%5Bwght%5D.ttf",
    "source sans": "https://raw.githubusercontent.com/google/fonts/main/ofl/sourcesans3/SourceSans3%5Bwght%5D.ttf",
    "work sans": "https://raw.githubusercontent.com/google/fonts/main/ofl/worksans/WorkSans%5Bwght%5D.ttf",
    "dm sans": "https://raw.githubusercontent.com/google/fonts/main/ofl/dmsans/DMSans%5Bopsz,wght%5D.ttf",
    "manrope": "https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/Manrope%5Bwght%5D.ttf",
}

_FONT_DIRS = [
    Path("workspace/fonts"),
    config.ROOT / "workspace" / "fonts",
    Path.home() / "Library" / "Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
]


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def find_font_file(family: str) -> str | None:
    """Locate a font file matching the family name across known dirs."""
    fam = _norm(family)
    if not fam:
        return None
    token = fam.replace(" ", "")
    for d in _FONT_DIRS:
        if not d or not Path(d).is_dir():
            continue
        for p in sorted(Path(d).rglob("*")):
            if p.suffix.lower() not in (".ttf", ".otf", ".ttc", ".woff2"):
                continue
            n = _norm(p.stem)
            if token in n.replace(" ", "") or n.replace(" ", "") in token:
                return str(p)
    return None


def ensure_font_file(family: str) -> str | None:
    """Find the font, fetching known open families into workspace/fonts if absent."""
    hit = find_font_file(family)
    if hit:
        return hit
    fam = _norm(family)
    url = _OPEN_FAMILIES.get(fam)
    if not url:
        for key, u in _OPEN_FAMILIES.items():
            if key in fam or fam in key:
                url = u
                break
    if not url:
        return None
    dest = config.WORKSPACE / "fonts" / f"{fam.replace(' ', '')}.ttf"
    try:
        import urllib.request

        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        return str(dest) if dest.exists() else None
    except Exception:
        return None


def _typo_page(p: str) -> bool:
    n = Path(p).name.lower()
    return bool(re.search(r"typo|font|type|text|writing|voice|copy", n))


def identify_fonts(page_paths: list[str], max_pages: int = 10) -> dict:
    """Vision pass over guideline pages; typography-relevant pages first."""
    pages = sorted(page_paths, key=lambda p: (not _typo_page(p), p))[:max_pages]
    if not pages:
        return {}
    best: dict = {"headline_font": "", "body_font": "", "weights": [], "notes": "", "confidence": 0.0}
    for p in pages:
        try:
            raw = llm.chat_vision(
                FONT_SYSTEM,
                [{"type": "text", "text": f"GUIDELINE PAGE: {Path(p).name}"}, llm.img_part(p, detail="high")],
                model="flash",
                json_mode=True,
            )
            import json

            data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M) or "{}")
        except Exception:
            continue
        conf = float(data.get("confidence") or 0)
        if conf >= float(best.get("confidence") or 0) and (data.get("headline_font") or data.get("body_font")):
            best = {
                "headline_font": (data.get("headline_font") or "").strip(),
                "body_font": (data.get("body_font") or "").strip(),
                "weights": [str(w) for w in (data.get("weights") or [])][:6],
                "notes": (data.get("notes") or "").strip(),
                "confidence": conf,
            }
        if best.get("headline_font") and best.get("body_font") and conf >= 0.8:
            break
    return best
