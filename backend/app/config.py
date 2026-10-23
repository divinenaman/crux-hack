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

# Image backend: "fal" | "cloudflare" | "litellm"
IMAGE_BACKEND = os.getenv("IMAGE_BACKEND", "cloudflare")

# fal.ai (queue API) — edit model paints the background from the wireframe
FAL_KEY = os.getenv("FAL_KEY", "")
FAL_IMAGE_MODEL = os.getenv("FAL_IMAGE_MODEL", "fal-ai/bytedance/seedream/v4/edit")  # edit (i2i) endpoint
FAL_T2I_MODEL = os.getenv("FAL_T2I_MODEL", "fal-ai/z-image/turbo")  # cheap drafts
# Background fill: "t2i" paints the scene from the verbal prompt ONLY (edit models copy
# any pixel reference — dashes/ghosts come out as literal boxes); "edit" keeps the old
# wireframe-reference path.
IMAGE_FILL_MODE = os.getenv("IMAGE_FILL_MODE", "t2i")
IMAGE_FILL_T2I_MODEL = os.getenv("IMAGE_FILL_T2I_MODEL", "fal-ai/bytedance/seedream/v4/text-to-image")

# Generation resolution tier for the fill stage: "1k" (default) | "2k" | "4k"
# Scales the base ratio sizes (1:1=1024, 4:5=1024x1280, 9:16=1024x1536, 16:9=1536x1024).
IMAGE_RES = os.getenv("IMAGE_RES", "1k").lower()
_RES_SCALE = {"1k": 1.0, "2k": 1.5, "4k": 2.0}.get(IMAGE_RES, 1.0)

def _res_scale() -> float:
    return _RES_SCALE

# Cloudflare Workers AI (free tier) — fallback image backend
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_KEY", "")
CF_T2I_MODEL = os.getenv("CF_T2I_MODEL", "@cf/black-forest-labs/flux-1-schnell")
CF_I2I_MODEL = os.getenv("CF_I2I_MODEL", "@cf/runwayml/stable-diffusion-v1-5-inpainting")

# Text/vision agent backend ("litellm" | "gemini" | "cloudflare"; "auto" = first with secrets)
LLM_TEXT_BACKEND = os.getenv("LLM_TEXT_BACKEND", "auto").lower()
CF_LLM_TEXT_MODEL = os.getenv("CF_LLM_TEXT_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
CF_LLM_VISION_MODEL = os.getenv("CF_LLM_VISION_MODEL", "@cf/meta/llama-4-scout-17b-16e-instruct")
GEMINI_KEY = os.getenv("GEMINI_KEY", "")
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite")
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.5-flash")


def resolve_text_backend() -> str:
    be = LLM_TEXT_BACKEND
    if be == "auto":
        be = (
            "litellm" if LITELLM_KEY
            else "gemini" if GEMINI_KEY
            else "cloudflare" if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN
            else "litellm"
        )
    return be

MAX_ASSET_REFS = int(os.getenv("MAX_ASSET_REFS", "2"))
ASSETS_PER_COMPOSITION = int(os.getenv("ASSETS_PER_COMPOSITION", "4"))  # fixed asset count per design
MAX_JUDGE_ROUNDS = int(os.getenv("MAX_JUDGE_ROUNDS", "2"))
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "low")
DEEP_PLAN = os.getenv("DEEP_PLAN", "0") == "1"  # 1 = thinking-model planning (slow, richer)
VARIANTS = 4
BRAND_FONT = os.getenv("BRAND_FONT", "Figtree")
BRAND_FONT_FALLBACK = "system-ui, sans-serif"
