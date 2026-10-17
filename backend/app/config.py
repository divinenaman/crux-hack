import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", ROOT / "workspace"))
BRANDS_DIR = WORKSPACE / "brands"
ASSETS_DIR = WORKSPACE / "assets"
LEGACY_JOBS_DIR = WORKSPACE / "jobs"
OUT_DIR = WORKSPACE / "out"
GRAMMAR_PATH = WORKSPACE / "grammar" / "grammar.json"
CATALOG_PATH = WORKSPACE / "catalog.json"

for d in (BRANDS_DIR, ASSETS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def brand_dir(brand_id: str) -> Path:
    d = BRANDS_DIR / brand_id
    for sub in ("assets", "jobs", "out", "grammar"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def brand_assets_dir(brand_id: str) -> Path:
    return brand_dir(brand_id) / "assets"


def brand_jobs_dir(brand_id: str) -> Path:
    return brand_dir(brand_id) / "jobs"


def brand_out_dir(brand_id: str) -> Path:
    return brand_dir(brand_id) / "out"


def brand_catalog_path(brand_id: str) -> Path:
    return brand_dir(brand_id) / "catalog.json"


def brand_grammar_path(brand_id: str) -> Path:
    return brand_dir(brand_id) / "grammar" / "grammar.json"


DEEPSEEK_PRO_KEY = os.getenv("DEEPSEEK_PRO_KEY", "")
DEEPSEEK_FLASH_KEY = os.getenv("DEEPSEEK_FLASH_KEY", "")
DEEPSEEK_PRO_BASE = os.getenv("DEEPSEEK_PRO_BASE", "https://crux-hackathon-swe.openai.azure.com/openai/v1/")
DEEPSEEK_FLASH_BASE = os.getenv("DEEPSEEK_FLASH_BASE", "https://crux-hackathon-eus2.openai.azure.com/openai/v1/")
DEEPSEEK_PRO_MODEL = os.getenv("DEEPSEEK_PRO_MODEL", "DeepSeek-V4-Pro")
DEEPSEEK_FLASH_MODEL = os.getenv("DEEPSEEK_FLASH_MODEL", "DeepSeek-V4.1-Flash")
OPENAI_IMAGE_KEY = os.getenv("OPENAI_IMAGE_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")

MAX_ASSET_REFS = 8
MAX_JUDGE_ROUNDS = 3
VARIANTS = 4
BRAND_FONT = os.getenv("BRAND_FONT", "Figtree")
BRAND_FONT_FALLBACK = "system-ui, sans-serif"
