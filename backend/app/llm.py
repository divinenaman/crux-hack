import base64
import mimetypes
import time
from pathlib import Path

from openai import OpenAI

from . import config
from .imutil import ensure_raster

_pro = None
_flash = None
_img = None
_vis = None


def pro():
    global _pro
    if _pro is None:
        _pro = OpenAI(base_url=config.DEEPSEEK_PRO_BASE, api_key=config.DEEPSEEK_PRO_KEY)
    return _pro


def flash():
    global _flash
    if _flash is None:
        _flash = OpenAI(base_url=config.DEEPSEEK_FLASH_BASE, api_key=config.DEEPSEEK_FLASH_KEY)
    return _flash


def image_client():
    global _img
    if _img is None:
        _img = OpenAI(api_key=config.OPENAI_IMAGE_KEY)
    return _img


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
            if "429" in msg or "rate" in msg.lower() or "timeout" in msg.lower() or "503" in msg:
                time.sleep(delay + i * 2)
                continue
            raise


def chat_text(system: str, user: str, model: str = "flash", json_mode: bool = False) -> str:
    client = pro() if model == "pro" else flash()
    name = config.DEEPSEEK_PRO_MODEL if model == "pro" else config.DEEPSEEK_FLASH_MODEL

    def run():
        kwargs = dict(
            model=name,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client.chat.completions.create(**kwargs)
        return r.choices[0].message.content or ""

    return _retry(run)


def chat_vision(system: str, parts: list[dict], model: str = "flash", json_mode: bool = False) -> str:
    client = flash()
    name = config.DEEPSEEK_FLASH_MODEL

    def run():
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": parts})
        kwargs = dict(model=name, messages=msgs, temperature=0.3)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client.chat.completions.create(**kwargs)
        return r.choices[0].message.content or ""

    return _retry(run)


def generate_image(
    prompt: str,
    ref_paths: list[str | Path] | None = None,
    size: str = "1024x1024",
    model: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
) -> bytes:
    client = image_client()
    mid = model or config.IMAGE_MODEL

    safe_refs: list[str] = []
    for p in ref_paths or []:
        try:
            safe_refs.append(ensure_raster(p))
        except Exception:
            continue

    def run():
        extra = {}
        if background:
            extra["background"] = background
        if output_format:
            extra["output_format"] = output_format
        if safe_refs:
            imgs = [open(p, "rb") for p in safe_refs]
            try:
                r = client.images.edit(model=mid, image=imgs, prompt=prompt, size=size, n=1, **extra)
            finally:
                for f in imgs:
                    f.close()
        else:
            r = client.images.generate(model=mid, prompt=prompt, size=size, n=1, **extra)
        return base64.b64decode(r.data[0].b64_json)

    return _retry(run)


def edit_image(
    prompt: str,
    src_path: str | Path,
    size: str = "1024x1024",
    mask_path: str | Path | None = None,
    model: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
) -> bytes:
    client = image_client()
    src = ensure_raster(src_path)
    mid = model or config.IMAGE_MODEL

    def run():
        extra = {}
        if background:
            extra["background"] = background
        if output_format:
            extra["output_format"] = output_format
        with open(src, "rb") as f:
            if mask_path and Path(mask_path).exists():
                with open(mask_path, "rb") as m:
                    r = client.images.edit(model=mid, image=[f], mask=m, prompt=prompt, size=size, n=1, **extra)
            else:
                r = client.images.edit(model=mid, image=[f], prompt=prompt, size=size, n=1, **extra)
        return base64.b64decode(r.data[0].b64_json)

    return _retry(run)
