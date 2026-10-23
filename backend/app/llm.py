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
    if config.resolve_text_backend() == "gemini" and config.GEMINI_KEY:
        return _gemini_ask(system, user, json_mode=json_mode)
    if config.resolve_text_backend() == "cloudflare" and _use_cf():
        return _cf_ask(system, user, json_mode=json_mode)

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
    if config.resolve_text_backend() == "gemini" and config.GEMINI_KEY:
        return _gemini_ask(system, parts, json_mode=json_mode)
    if config.resolve_text_backend() == "cloudflare" and _use_cf():
        return _cf_ask(system, parts, json_mode=json_mode, vision=True)

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


# --- text+vision backends ----------------------------------------------------
_GLITCHY = re.compile(r"^<\|begin_of_box\|>|^</s>$|\s+$")


def _cf_json_fields(payload) -> str:
    """Worker AI /ai/run/<chat-model> returns {'result': {'response': '...'}}."""
    res = payload.get("result") or {}
    txt = res.get("response") or res.get("text") or ""
    if not isinstance(txt, str):
        txt = str(txt)
    return txt


def _cf_text_call(model: str, messages: list[dict], max_tokens: int = 4096, temperature: float = 0.4, json_mode: bool = False) -> str:
    import json as _json

    import httpx

    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}
    body: dict = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    def run():
        r = httpx.post(url, headers=headers, json=body, timeout=240.0)
        if r.status_code == 429 or r.status_code >= 500:
            raise RuntimeError(f"cf transient {r.status_code}: {r.text[:120]}")
        if r.status_code != 200:
            raise RuntimeError(f"cf {r.status_code}: {r.text[:300]}")
        return _cf_json_fields(r.json())

    return _retry(run, attempts=3)


def _cf_ask(system: str, user, size_notes: str = "", json_mode: bool = False, vision: bool = False) -> str:
    """CF Workers AI text/vision call. `user` may be a string or a content-parts list
    ({"type": "text"|"image_url", ...}); image parts are flattened to messages."""
    model = config.CF_LLM_VISION_MODEL if vision else config.CF_LLM_TEXT_MODEL
    user_txt_parts: list[str] = []
    extra_imgs: list[dict] = []
    if isinstance(user, str):
        user_txt_parts.append(user)
    else:
        for p in user:
            if not isinstance(p, dict):
                user_txt_parts.append(str(p))
                continue
            if p.get("type") == "text":
                user_txt_parts.append((p.get("text") or ""))
            elif p.get("type") == "image_url":
                extra_imgs.append(p)
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    # CF vision endpoints accept image_url parts directly, so assemble OpenAI-style content
    if extra_imgs and vision:
        content: list[dict] = [{"type": "text", "text": "\n".join(t for t in user_txt_parts if t) + (f"\n{size_notes}" if size_notes else "")}]
        content.extend(extra_imgs)
        msgs.append({"role": "user", "content": content})
    else:
        txt = "\n".join(t for t in user_txt_parts if t)
        if size_notes:
            txt += f"\n{size_notes}"
        msgs.append({"role": "user", "content": txt})
    return _cf_text_call(model, msgs, json_mode=json_mode)


def _gemini_text_call(model: str, parts: list[dict], system: str = "", json_mode: bool = False) -> str:
    """Gemini generateContent: parts are {"text": str} or {"inline_data": {"mime_type", "data"}}."""
    import base64
    import json as _json

    import httpx

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": config.GEMINI_KEY, "Content-Type": "application/json"}
    body: dict = {"contents": [{"role": "user", "parts": parts}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    gc: dict = {"maxOutputTokens": 8192, "temperature": 0.4}
    if json_mode:
        gc["responseMimeType"] = "application/json"
    body["generationConfig"] = gc

    def run():
        r = httpx.post(url, headers=headers, json=body, timeout=240.0)
        if r.status_code == 429 or r.status_code >= 500:
            raise RuntimeError(f"gemini transient {r.status_code}: {r.text[:140]}")
        if r.status_code != 200:
            raise RuntimeError(f"gemini {r.status_code}: {r.text[:300]}")
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        out = "".join(p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or []))
        if not out:
            raise RuntimeError(f"gemini empty: {str(data)[:220]}")
        return out

    return _retry(run, attempts=3)


def _gemini_ask(system: str, user, json_mode: bool = False) -> str:
    parts: list[dict] = []
    if isinstance(user, str):
        parts.append({"text": user})
    else:
        for p in user:
            if not isinstance(p, dict):
                parts.append({"text": str(p)})
            elif p.get("type") == "text":
                if p.get("text"):
                    parts.append({"text": p["text"]})
            elif p.get("type") == "image_url":
                src = p.get("image_url", {}).get("url", "")
                m = re.match(r"^data:([^;]+);base64,(.+)$", src, re.S)
                if m:
                    parts.append({"inline_data": {"mime_type": m.group(1), "data": m.group(2)}})
    return _gemini_text_call(config.GEMINI_TEXT_MODEL, parts, system=system, json_mode=json_mode)


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


# --- fal.ai queue API (image backend) ---------------------------------------
def _fal_run(model: str, body: dict, timeout: float = 300.0) -> bytes:
    """fal queue: submit → poll → fetch result → download first image."""
    import httpx

    key = config.FAL_KEY
    if not key:
        raise RuntimeError("FAL_KEY not configured")
    poll = 1.0
    url = f"https://queue.fal.run/{model}"
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}

    def run():
        r = httpx.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code in (429, 500, 502, 503):
            raise RuntimeError(f"fal transient {r.status_code}: {r.text[:120]}")
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"fal submit {r.status_code}: {r.text[:400]}")
        j = r.json()
        rid = j.get("request_id", "")
        status_url = j.get("status_url") or f"https://queue.fal.run/{model}/requests/{rid}/status"
        response_url = j.get("response_url") or f"https://queue.fal.run/{model}/requests/{rid}"
        t0 = time.time()
        while True:
            s = httpx.get(status_url, headers={"Authorization": f"Key {key}"}, timeout=30.0)
            st_code = s.status_code
            if st_code in (429, 500, 502, 503):
                if time.time() - t0 > 240:
                    raise RuntimeError(f"fal status timeout: {st_code}")
                time.sleep(3.0)
                continue
            if st_code not in (200, 202):
                raise RuntimeError(f"fal status {st_code}: {s.text[:300]}")
            st = s.json().get("status", "")
            if st == "COMPLETED":
                break
            if st == "FAILED" or time.time() - t0 > 420:
                raise RuntimeError(f"fal request {st.lower()} after {time.time() - t0:.0f}s")
            time.sleep(poll)
        g = httpx.get(response_url, headers={"Authorization": f"Key {key}"}, timeout=60.0)
        if g.status_code != 200:
            raise RuntimeError(f"fal result {g.status_code}: {g.text[:300]}")
        imgs = g.json().get("images") or []
        if not imgs:
            raise RuntimeError(f"fal result carried no image: {str(g.json())[:300]}")
        src = imgs[0].get("url") or ""
        if src.startswith("data:"):
            return base64.b64decode(src.split("base64,", 1)[1])
        img = httpx.get(src, timeout=120.0)
        if img.status_code != 200:
            raise RuntimeError(f"fal image download {img.status_code}")
        return img.content

    return _retry(run, attempts=3)


def _fal_data_uri(path: str | Path) -> str:
    mime, data = _b64(path)
    return f"data:{mime};base64,{data}"


def _fal_size(size: str) -> dict:
    """1024x1024 → {"width":1024,"height":1024} (models snap to their grids)."""
    try:
        w, h = size.lower().split("x")
        return {"width": max(256, int(w)), "height": max(256, int(h))}
    except Exception:
        return {"width": 1024, "height": 1024}


_FAL_AR = {"1:1": "1:1", "4:5": "4:5", "3:4": "3:4", "9:16": "9:16", "16:9": "16:9", "2:3": "2:3", "3:2": "3:2", "5:4": "5:4"}


_GPT_IMG_SIZE_MAP = {
    # fal gpt-image-1/edit-image only supports 3 fixed sizes + "auto"
    # pick the nearest supported value by area
    "1024x1024": "1024x1024",
    "1024x1280": "1024x1536",  # 4:5 → nearest portrait
    "1024x1536": "1024x1536",  # 9:16
    "1536x1024": "1536x1024",  # 16:9
    "1280x1024": "1536x1024",
}


def _gpt_img_size(size: str) -> str:
    """Map any WxH string to the nearest size gpt-image-1/edit-image accepts."""
    return _GPT_IMG_SIZE_MAP.get(size.lower(), "1024x1024")


def _fal_body_gpt_edit(prompt: str, src: str, size: str) -> dict:
    """Body for fal-ai/gpt-image-1/edit-image: opaque bg, low quality.
    Wireframe reference is sent so the model knows where elements are placed."""
    return {
        "prompt": prompt,
        "image_urls": [_fal_data_uri(src)],
        "image_size": _gpt_img_size(size),
        "quality": "low",
        "background": "opaque",   # transparent caused alpha≈0; opaque returns full scene
        "output_format": "png",
    }


def _fal_body_edit(model: str, prompt: str, src: str, size: str, strength: float | None = None) -> dict:
    """Map the pipeline's edit_image call onto the chosen fal edit endpoint."""
    data = _fal_data_uri(src)
    if "gpt-image-1" in model:  # OpenAI gpt-image-1 via fal — low quality, transparent bg
        return _fal_body_gpt_edit(prompt, src, size)
    if "/edit-image" in model:  # blackforestlabs flux-3 (klein) edit
        return {
            "prompt": prompt,
            "image_urls": [data],
            "image_size": _fal_size(size),
            "enable_prompt_expansion": False,
            "output_format": "png",
        }
    if "z-image" in model and "image-to-image" in model:  # diffusion i2i w/ strength
        return {
            "prompt": prompt,
            "image_url": data,
            "image_size": _fal_size(size),
            "num_inference_steps": 8,
            "strength": strength if strength is not None else 0.6,
            "output_format": "png",
        }
    if "seedream" in model:  # bytedance v4/v5 edit — exact custom size
        return {"prompt": prompt, "image_urls": [data], "image_size": _fal_size(size), "max_images": 1}
    if "nano-banana" in model:  # gemini image — aspect-ratio enum only
        w, h = (int(v) for v in size.lower().split("x"))
        from math import gcd

        g = gcd(w, h)
        ar = f"{w // g}:{h // g}"
        return {"prompt": prompt, "image_urls": [data], "aspect_ratio": _FAL_AR.get(ar, "auto"), "output_format": "png"}
    if "kontext" in model:  # flux kontext — instruction editor
        return {"prompt": prompt, "image_url": data, "image_size": _fal_size(size)}
    if "qwen" in model and "edit" in model:  # qwen image edit family (v3 takes image_urls)
        return {"prompt": prompt, "image_urls": [data], "image_size": _fal_size(size)}
    # unknown edit endpoint — try the common shape and let it fail loudly
    return {"prompt": prompt, "image_urls": [data], "image_size": _fal_size(size)}


def _fal_model() -> str:
    return config.FAL_IMAGE_MODEL


def _fal_body_t2i(model: str, prompt: str, size: str) -> dict:
    if "gpt-image-1" in model:
        return {
            "prompt": prompt,
            "image_size": _gpt_img_size(size),
            "quality": "low",
            "background": "opaque",   # t2i fill = full scene, not transparent cutout
            "output_format": "png",
        }
    if "z-image" in model:
        return {"prompt": prompt, "image_size": _fal_size(size), "num_inference_steps": 8, "output_format": "png"}
    return {"prompt": prompt, "image_size": _fal_size(size)}


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


def _cf_edit(prompt: str, src: str, size: str, mask_path: str | Path | None = None, strength: float | None = None, model: str | None = None) -> bytes:
    """Masked inpaint via runway sd1.5-inpainting (white = repaint region)."""
    from io import BytesIO

    from PIL import Image, ImageOps

    cf_model = model or config.CF_I2I_MODEL
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
    return _cf_run(cf_model, body)


def _use_cf() -> bool:
    return bool(config.CLOUDFLARE_ACCOUNT_ID) and bool(config.CLOUDFLARE_API_TOKEN)


def _use_fal() -> bool:
    return config.IMAGE_BACKEND == "fal" and bool(config.FAL_KEY)


def _backend_of(backend: str | None) -> str:
    """Call-scoped backend override; None → the configured IMAGE_BACKEND."""
    return backend or config.IMAGE_BACKEND


def _edit_model_of(backend: str, model: str | None) -> str:
    if backend == "fal":
        return model or config.FAL_IMAGE_MODEL
    return model or config.CF_I2I_MODEL


def generate_image(
    prompt: str,
    ref_paths: list[str | Path] | None = None,
    size: str = "1024x1024",
    model: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
    quality: str | None = None,
    backend: str | None = None,
) -> bytes:
    safe_refs: list[str] = []
    for p in ref_paths or []:
        try:
            safe_refs.append(ensure_raster(p))
        except Exception:
            continue
    be = _backend_of(backend)
    if be == "fal" and config.FAL_KEY:
        return _fal_run(model or config.FAL_T2I_MODEL, _fal_body_t2i(model or config.FAL_T2I_MODEL, prompt, size))
    if be == "cloudflare" and _use_cf():
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
    backend: str | None = None,
) -> bytes:
    src = ensure_raster(src_path)
    be = _backend_of(backend)
    if be == "fal" and config.FAL_KEY:
        selected_model = _edit_model_of(be, model)
        return _fal_run(
            selected_model,
            _fal_body_edit(selected_model, prompt, src, size, strength=strength),
        )
    if be == "cloudflare" and _use_cf():
        return _cf_edit(prompt, src, size, mask_path=mask_path, strength=strength, model=model)
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
