import re
from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, llm
from ..models import Brief, Grammar
from ..compose import prompts

_LOGO_ROLES = ("logo", "logo_footer", "footer")


def compose(brief: Brief, grammar: Grammar, contact_sheet: str, out_path: Path, refs: list[str], brand_id: str = "", wireframe: str = "") -> str:
    prompt = prompts.build_prompt(brief, grammar, ref_note="(numbered contact sheet + raw refs + wireframe attached)", brand_id=brand_id)
    # speed: contact sheet already carries the assets — attach at most MAX_ASSET_REFS raw refs.
    # the wireframe (what we expect) is always attached — that is the consistency mechanism.
    all_refs = ([wireframe] if wireframe else []) + [contact_sheet] + refs[: config.MAX_ASSET_REFS]
    all_refs = [r for r in all_refs if r and Path(r).exists() and Path(r).stat().st_size > 0]
    size = prompts.size_for(brief.ratio)
    png = llm.generate_image(prompt, ref_paths=all_refs, size=size)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return str(out_path)


def apply_fix(brief: Brief, src: Path, out_path: Path, fix: str) -> str:
    prompt = prompts.build_fix_prompt(brief, fix)
    png = llm.edit_image(prompt, src, size=prompts.size_for(brief.ratio))
    out_path.write_bytes(png)
    return str(out_path)


def parse_frac_rects(text: str) -> list[tuple[float, float, float, float]]:
    out = []
    pair = r"([0-9.]+)\s*[-–—to]+\s*([0-9.]+)"
    for pat in (
        re.compile(rf"x[=:\s]*{pair}\s*,\s*y[=:\s]*{pair}", re.I),
        re.compile(rf"y[=:\s]*{pair}\s*,\s*x[=:\s]*{pair}", re.I),
    ):
        for m in pat.finditer(text or ""):
            a0, a1, b0, b1 = (float(m.group(i)) for i in range(1, 5))
            if pat.pattern.startswith("y"):
                y0, y1, x0, x1 = a0, a1, b0, b1
            else:
                x0, x1, y0, y1 = a0, a1, b0, b1
            if 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1:
                rect = (x0, y0, x1 - x0, y1 - y0)
                if rect not in out:
                    out.append(rect)
    return out


def build_strip_mask(
    brief: Brief,
    src: Path,
    out_path: Path,
    extra_rects: list[tuple[float, float, float, float]] | None = None,
    pad: float = 0.035,
) -> str:
    im = Image.open(src)
    W, H = im.size
    mask = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    draw = ImageDraw.Draw(mask)

    rects: list[tuple[float, float, float, float]] = []
    for z in brief.zones:
        if z.style.get("replace") is False:
            continue  # element stays baked — do not erase what we will not replace
        from .textfit import _is_replace_role

        if not _is_replace_role(z.role):
            continue  # wireframe layout zones (bg/photo/charm…) are never erased
        content = prompts.text_of(brief, z.role) or z.content
        if content or z.role in _LOGO_ROLES:
            rects.append(tuple(z.rect))
    rects.extend(extra_rects or [])

    for x, y, w, h in rects:
        x0 = max(0.0, x - pad) * W
        y0 = max(0.0, y - pad) * H
        x1 = min(1.0, x + w + pad) * W
        y1 = min(1.0, y + h + pad) * H
        draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(out_path)
    return str(out_path)


def _composite_edit(src_path: Path, edited_png: bytes, mask_path: Path, out_path: Path) -> None:
    """Enforce 'everything else pixel-identical' deterministically.

    The image model drifts whole-canvas even with a mask — so we keep the
    original everywhere except inside the masked windows, where the model's
    inpaint is used (feathered 2px at the boundary)."""
    from io import BytesIO

    from PIL import ImageFilter

    src = Image.open(src_path).convert("RGBA")
    edt = Image.open(BytesIO(edited_png)).convert("RGBA")
    if edt.size != src.size:
        edt = edt.resize(src.size)
    mask = Image.open(mask_path).convert("RGBA")
    keep = mask.split()[3].filter(ImageFilter.GaussianBlur(2))  # 255 = keep original
    out = Image.composite(src, edt, keep)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.convert("RGB").save(out_path)


def strip_text_and_logo(
    brief: Brief,
    src: Path,
    out_path: Path,
    extra_rects: list[tuple[float, float, float, float]] | None = None,
    extra_notes: str = "",
) -> str:
    mask = out_path.with_name(f"{out_path.stem}_mask.png")
    build_strip_mask(brief, src, mask, extra_rects=extra_rects)
    prompt = prompts.build_strip_prompt(brief)
    if extra_notes:
        prompt += "\n\nConfirmed leftovers still visible — remove ONLY these inside the editable region:\n" + extra_notes
    png = llm.edit_image(prompt, src, size=prompts.size_for(brief.ratio), mask_path=mask)
    _composite_edit(Path(src), png, mask, Path(out_path))
    return str(out_path)
