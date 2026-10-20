"""Model transport — everything through the LiteLLM gateway.

- text + vision: model `open-fast` (chat completions)
- image gen:     model `gemini-3.1-pro` (chat completions; the reply carries the image)

Signatures are kept identical to the old multi-provider client so the rest of
the pipeline is untouched.
"""
import base64
import mimetypes
import re
import time
from pathlib import Path

from openai import OpenAI

from . import config
from .imutil import ensure_raster

_client = None

_IMG_SYS = (
    "You are an image generator inside an ad-creation pipeline. "
    "Output ONLY the generated image — no commentary, no markdown text besides the image."
)


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=config.LLM_BASE, api_key=config.LITELLM_KEY or "no-key", timeout=300.0)
    return _client


# --- backwards-compatible accessors -----------------------------------------
def pro():
    return client()


def flash():
    return client()


def image_client():
    return client()


def _b64(path: str | Path) -> tuple[str, str]:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return mime, base64.b64encode(p.read_bytes()).decode()


def img_part(path: str | Path, detail: str = "high") -> dict:
    mime, data = _b64(path)
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}", "detail": detail}}


def _retry(fn, attempts: int = 4):
    delay = 2.0
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            msg = str(e)
            if "429" in msg or "rate" in msg.lower() or "timeout" in msg.lower() or "503" in msg or "502" in msg:
                time.sleep(delay + i * 2)
                continue
            raise


def _resolve_model(model: str) -> str:
    # "flash"/"thinking"/"pro" are legacy aliases for the configured default
    return config.LLM_MODEL if model in ("flash", "thinking", "pro", "") else model


def chat_text(system: str, user: str, model: str = "flash", json_mode: bool = False, timeout: float = 300.0, attempts: int = 4, temperature: float = 0.4) -> str:
    def run():
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
        kwargs = dict(model=_resolve_model(model), messages=msgs, temperature=temperature, max_tokens=8192, timeout=timeout)
        if kwargs["model"].startswith("open"):
            kwargs["reasoning_effort"] = "none"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client().chat.completions.create(**kwargs)
        return r.choices[0].message.content or ""

    return _retry(run, attempts=attempts)


def chat_vision(system: str, parts: list[dict], model: str = "flash", json_mode: bool = False, timeout: float = 300.0, attempts: int = 4) -> str:
    def run():
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": parts})
        kwargs = dict(model=_resolve_model(model), messages=msgs, temperature=0.3, max_tokens=8192, timeout=timeout)
        if kwargs["model"].startswith("open"):
            kwargs["reasoning_effort"] = "none"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client().chat.completions.create(**kwargs)
        return r.choices[0].message.content or ""

    return _retry(run, attempts=attempts)


def chat_agent(
    system: str,
    user: str,
    tools: list[dict],
    dispatch,  # (name: str, args: dict) -> str
    model: str = "pro",
    max_rounds: int = 8,
    timeout: float = 300.0,
) -> str:
    """Tool-calling loop: the model calls tools (e.g. read_asset to view a brand
    asset) and finishes with its final answer. Returns the final assistant text.
    The last round forces a plain answer (no more tool calls) so browsing can
    never starve the conclusion."""
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})
    rounds = max(1, max_rounds)
    for i in range(rounds):
        last = i == rounds - 1

        def run():
            kwargs = dict(model=_resolve_model(model), messages=msgs, temperature=0.4, max_tokens=8192, timeout=timeout)
            if kwargs["model"].startswith("open"):
                kwargs["reasoning_effort"] = "none"
            if tools:
                kwargs["tools"] = tools
                if last:
                    kwargs["tool_choice"] = "none"
            return client().chat.completions.create(**kwargs)

        r = _retry(run, attempts=3)
        m = r.choices[0].message
        if m.tool_calls:
            msgs.append(
                {
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                        for tc in m.tool_calls
                    ],
                }
            )
            for tc in m.tool_calls:
                try:
                    import json as _json

                    args = _json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                try:
                    result = dispatch(tc.function.name, args)
                except Exception as e:
                    result = f"tool error: {e}"
                if isinstance(result, list):
                    # content parts (e.g. an asset image) — tool ack + a user turn carrying them
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": "(see the attached image)"})
                    msgs.append({"role": "user", "content": result})
                else:
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
            continue
        return m.content or ""
    return ""


# --- image generation through chat ------------------------------------------
_B64_RE = re.compile(r"data:image/[a-zA-Z+]+;base64,([A-Za-z0-9+/=\s]{64,})")
_MD_RE = re.compile(r"!\[[^\]]*\]\((data:image/[a-zA-Z+]+;base64,([A-Za-z0-9+/=\s]{64,}))\)")
_RAW_B64_RE = re.compile(r"^([A-Za-z0-9+/]{512,}={0,2})$")


def _decode_b64(s: str) -> bytes:
    return base64.b64decode(re.sub(r"\s+", "", s))


def _extract_image(msg) -> bytes:
    """Pull image bytes out of a chat reply — LiteLLM/gemini serve them in
    several shapes (message.images, content parts, or markdown data URIs)."""
    # 1) litellm-style message.images
    for im in getattr(msg, "images", None) or []:
        if isinstance(im, dict):
            url = (im.get("image_url") or {}).get("url") if isinstance(im.get("image_url"), dict) else im.get("image_url") or im.get("url") or im.get("b64_json") or ""
        else:
            url = getattr(im, "url", "") or ""
        s = str(url)
        if "base64," in s:
            return _decode_b64(s.split("base64,", 1)[1])
        if s.startswith("http"):
            import urllib.request

            return urllib.request.urlopen(s, timeout=120).read()

    content = msg.content
    # 2) structured content parts
    if isinstance(content, list):
        for part in content:
            p = part if isinstance(part, dict) else getattr(part, "model_dump", lambda: {})()
            t = p.get("type", "")
            if t in ("image_url", "image", "input_image"):
                url = p.get("image_url", {})
                s = url.get("url", "") if isinstance(url, dict) else str(url or p.get("url") or "")
                if "base64," in s:
                    return _decode_b64(s.split("base64,", 1)[1])
            if t in ("text", "") and isinstance(p.get("text"), str):
                b = _extract_image_from_text(p["text"])
                if b:
                    return b
        raise ValueError("no image in structured content parts")

    # 3) text with embedded data URI / markdown / raw b64
    b = _extract_image_from_text(str(content or ""))
    if b:
        return b
    raise ValueError("model reply carried no image")


def _extract_image_from_text(text: str) -> bytes | None:
    m = _MD_RE.search(text) or _B64_RE.search(text)
    if m:
        try:
            return _decode_b64(m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else m.group(1))
        except Exception:
            pass
    stripped = text.strip().strip("`")
    m = _RAW_B64_RE.match(stripped)
    if m:
        try:
            return _decode_b64(m.group(1))
        except Exception:
            pass
    return None


def _chat_image(prompt: str, ref_paths: list[str | Path] | None = None, size: str = "", system: str = _IMG_SYS) -> bytes:
    content: list[dict] = [{"type": "text", "text": (prompt + (f"\n\nCanvas size: {size} px." if size else "")).strip()}]
    for p in ref_paths or []:
        try:
            content.append(img_part(p))
        except Exception:
            continue

    def run():
        r = client().chat.completions.create(
            model=config.IMAGE_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            temperature=0.7,
            max_tokens=8192,
        )
        return _extract_image(r.choices[0].message)

    return _retry(run, attempts=3)


# --- Cloudflare Workers AI (free tier) image backend ------------------------
def _cf_run(model: str, body: dict) -> bytes:
    import json as _json

    import httpx

    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}

    def run():
        r = httpx.post(url, headers=headers, json=body, timeout=180.0)
        if r.status_code == 429 or r.status_code >= 500:
            raise RuntimeError(f"cf transient {r.status_code}: {r.text[:120]}")
        if r.status_code != 200:
            raise RuntimeError(f"cf {r.status_code}: {r.text[:300]}")
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            data = r.json()
            res = data.get("result") or {}
            img = res.get("image") or ""
            if img:
                return base64.b64decode(img)
            raise RuntimeError(f"cf json carried no image: {str(data)[:200]}")
        return r.content

    return _retry(run, attempts=3)


def _cf_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().split("x")
        return (max(256, min(1536, int(w) // 8 * 8)), max(256, min(1536, int(h) // 8 * 8)))
    except Exception:
        return (1024, 1024)


def _clamp_prompt(p: str) -> str:
    # flux-1-schnell (and the inpaint model) reject prompts > 2048 chars
    return p if len(p) <= 2048 else p[:2040].rsplit(" ", 1)[0]


def _cf_generate(prompt: str, ref_paths: list[str | Path] | None = None, size: str = "1024x1024") -> bytes:
    # schnell t2i wins the quality bake-off (dreamshaper i2i produced mush);
    # slot wants/placement are already spelled out in the prompt by the caller
    size_hint = f" Canvas: {size} px." if size else ""
    body = {"prompt": _clamp_prompt(prompt + size_hint)}
    return _cf_run(config.CF_T2I_MODEL, body)


def _cf_edit(prompt: str, src: str, size: str, mask_path: str | Path | None = None, strength: float | None = None) -> bytes:
    """Masked inpaint via runway sd1.5-inpainting (white = repaint region)."""
    from io import BytesIO

    from PIL import Image, ImageOps

    init = Path(src).read_bytes()
    if mask_path and Path(mask_path).exists():
        # our masks: alpha 255 = keep original → invert alpha for "repaint here"
        m = Image.open(mask_path).convert("RGBA")
        repaint = ImageOps.invert(m.split()[3]).convert("L")
        buf = BytesIO()
        repaint.save(buf, format="PNG")
        strength = strength if strength is not None else 0.7
    else:
        # unmasked (global fix/redraw): repaint everything, gentle strength = img2img
        im = Image.open(BytesIO(init))
        buf = BytesIO()
        Image.new("L", im.size, 255).save(buf, format="PNG")
        strength = strength if strength is not None else 0.45
    body = {
        "prompt": _clamp_prompt(prompt + (f" Canvas: {size} px." if size else "")),
        "image": list(init),
        "mask": list(buf.getvalue()),
        "strength": strength,
    }
    return _cf_run(config.CF_I2I_MODEL, body)


def _use_cf() -> bool:
    return (
        config.IMAGE_BACKEND == "cloudflare"
        and bool(config.CLOUDFLARE_ACCOUNT_ID)
        and bool(config.CLOUDFLARE_API_TOKEN)
    )


def generate_image(
    prompt: str,
    ref_paths: list[str | Path] | None = None,
    size: str = "1024x1024",
    model: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
    quality: str | None = None,
) -> bytes:
    safe_refs: list[str] = []
    for p in ref_paths or []:
        try:
            safe_refs.append(ensure_raster(p))
        except Exception:
            continue
    if _use_cf():
        return _cf_generate(prompt, safe_refs, size=size)
    return _chat_image(prompt, safe_refs, size=size)


def edit_image(
    prompt: str,
    src_path: str | Path,
    size: str = "1024x1024",
    mask_path: str | Path | None = None,
    strength: float | None = None,
    model: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
    quality: str | None = None,
) -> bytes:
    src = ensure_raster(src_path)
    if _use_cf():
        return _cf_edit(prompt, src, size, mask_path=mask_path, strength=strength)
    refs: list[str | Path] = [src]
    p = prompt
    if mask_path and Path(mask_path).exists():
        refs.append(mask_path)
        p += (
            "\n\nA second image is attached: the edit mask (white = keep exactly as-is, "
            "black = editable region). Change pixels ONLY inside the editable region."
        )
    p += "\nRecreate the full canvas, preserving everything outside the edited region exactly."
    return _chat_image(p, refs, size=size)
