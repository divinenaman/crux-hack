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

# LiteLLM gateway (single endpoint for text/vision + image gen)
LITELLM_KEY = os.getenv("LITELLM_KEY", "")
LLM_BASE = os.getenv("LLM_BASE", "https://grid.ai.juspay.net").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "open-fast")  # text + vision
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-3.1-pro")  # via litellm chat (fallback)

# Cloudflare Workers AI (free tier) — primary image backend
IMAGE_BACKEND = os.getenv("IMAGE_BACKEND", "cloudflare")  # "cloudflare" | "litellm"
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_KEY", "")
CF_T2I_MODEL = os.getenv("CF_T2I_MODEL", "@cf/black-forest-labs/flux-1-schnell")
CF_I2I_MODEL = os.getenv("CF_I2I_MODEL", "@cf/runwayml/stable-diffusion-v1-5-inpainting")

MAX_ASSET_REFS = int(os.getenv("MAX_ASSET_REFS", "2"))
ASSETS_PER_COMPOSITION = int(os.getenv("ASSETS_PER_COMPOSITION", "4"))  # fixed asset count per design
MAX_JUDGE_ROUNDS = int(os.getenv("MAX_JUDGE_ROUNDS", "2"))
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "low")
DEEP_PLAN = os.getenv("DEEP_PLAN", "0") == "1"  # 1 = thinking-model planning (slow, richer)
VARIANTS = 4
BRAND_FONT = os.getenv("BRAND_FONT", "Figtree")
BRAND_FONT_FALLBACK = "system-ui, sans-serif"
