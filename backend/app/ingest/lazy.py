import json
import re
import uuid
from pathlib import Path

from .. import config, llm, store
from ..models import Asset

EXTRACT_SYSTEM = """You isolate one brand element from a source image. Output JSON:
{"element": {"name": str, "semantic": str, "tags": [str], "colors": [str], "usage": str, "role_hints": [str]}}
Also you will be asked to EDIT the image to extract it. Keep identity exact: same curves, same colours.
"""


def extract_element(source_png: str, description: str, instructions: str, name_hint: str = "") -> Asset:
    src = Path(source_png)
    prompt = (
        f"{EXTRACT_SYSTEM}\n"
        f"Extract ONLY this element: {description}. {instructions}\n"
        "Remove every other element, labels, and background clutter. "
        "Output the element alone on a plain white background, centered, preserving exact shape and colours."
    )
    png_bytes = llm.edit_image(prompt, src, size="1024x1024")
    aid = re.sub(r"[^a-zA-Z0-9_-]", "_", (name_hint or description)[:40]).strip("_").lower() or uuid.uuid4().hex[:8]
    aid = f"lazy_{aid}"
    dest = config.ASSETS_DIR / f"{aid}.png"
    dest.write_bytes(png_bytes)

    meta_raw = llm.chat_vision(
        "Describe the extracted element as JSON {\"element\":{\"name\":str,\"semantic\":str,\"tags\":[str],\"colors\":[str],\"usage\":str,\"role_hints\":[str]}}",
        [llm.img_part(dest)],
        model="flash",
        json_mode=True,
    )
    try:
        meta = json.loads(re.sub(r"^```(?:json)?|```$", "", meta_raw.strip(), flags=re.M)).get("element", {})
    except Exception:
        meta = {"name": name_hint or description}

    from .classify import _as_list, _as_str

    asset = Asset(
        id=aid,
        name=_as_str(meta.get("name", name_hint or description)),
        kind="charm" if "charm" in _as_list(meta.get("tags")) else "single",
        tags=_as_list(meta.get("tags")),
        colors=_as_list(meta.get("colors")),
        usage=_as_str(meta.get("usage", instructions)),
        role_hints=_as_list(meta.get("role_hints")) or ["accent"],
        semantic=_as_str(meta.get("semantic", "")),
        png=str(dest),
        source=src.name,
        directly_usable=True,
        exact_required=True,
    )
    store.upsert_assets([asset])
    return asset
