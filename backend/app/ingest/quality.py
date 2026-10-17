import re
from pathlib import Path

import numpy as np
from PIL import Image

from ..imutil import ensure_raster
from ..models import Asset, Grammar


def verify_quality(path: str | Path) -> dict:
    issues = []
    score = 100.0
    p = Path(path)
    try:
        with Image.open(ensure_raster(p)) as im:
            w, h = im.size
            if min(w, h) < 48:
                issues.append(f"low resolution {w}x{h}")
                score -= 30
            if min(w, h) < 128:
                score -= 10
            gray = np.asarray(im.convert("L"), dtype=np.float32)
            var = float(gray.var())
            if var < 12:
                issues.append(f"flat/blurry content (variance {var:.0f})")
                score -= 25
            rgba = im.convert("RGBA")
            alpha = np.asarray(rgba)[:, :, 3]
            if (alpha < 10).mean() > 0.985:
                issues.append("almost fully transparent")
                score -= 40
            if p.stat().st_size < 800:
                issues.append("tiny file size")
                score -= 15
    except Exception as e:
        issues.append(f"unreadable: {e}")
        score = 0
    return {"ok": not issues, "score": max(0.0, round(score, 1)), "issues": issues}


def dominant_colors(path: str | Path, k: int = 4) -> list[str]:
    try:
        with Image.open(ensure_raster(path)) as im:
            im = im.convert("RGBA").resize((64, 64))
            arr = np.asarray(im)
            mask = arr[:, :, 3] > 32
            px = arr[:, :, :3][mask]
            if len(px) == 0:
                return []
            q = (px // 48 * 48).astype(np.uint8)
            uniq, counts = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
            order = np.argsort(-counts)[:k]
            out = []
            for i in order:
                r, g, b = uniq[i]
                out.append(f"#{r:02x}{g:02x}{b:02x}")
            return out
    except Exception:
        return []


_KIND_USE = {
    "logo": ["branding", "footer lockup"],
    "template": ["background", "layout base"],
    "charm": ["hero motif", "storytelling icon"],
    "bloom": ["accent shape", "photo mask", "pattern"],
    "illustration": ["scene", "hero visual"],
    "photo-scene": ["photography", "hero visual"],
    "ui-shot": ["product proof"],
    "vector": ["illustration", "accent"],
    "grid-cell": ["accent shape"],
    "single": ["accent"],
}


def use_cases_for(asset: Asset) -> list[str]:
    out = list(asset.role_hints) + _KIND_USE.get(asset.kind, [])
    for w in (asset.semantic or "").split(","):
        w = w.strip()
        if w and len(w) < 24:
            out.append(w)
    seen, uniq = set(), []
    for u in out:
        u = u.strip().lower()
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:10]


def rule_refs_for(asset: Asset, grammar: Grammar) -> list[str]:
    hay = f"{asset.kind} {asset.name} {asset.semantic} {' '.join(asset.tags)} {asset.folder}".lower()
    refs = []
    for r in grammar.context_rules:
        tokens = [t for t in re.split(r"\W+", (r.when or "").lower()) if len(t) > 2]
        if tokens and any(t in hay for t in tokens):
            refs.append(r.name)
    for t in grammar.techniques:
        blob = f"{t.name} {t.applies_to}".lower()
        if any(tok in hay for tok in (asset.kind, "bloom", "charm", "photo")) and any(w in hay for w in blob.split() if len(w) > 3):
            refs.append(t.name)
    return list(dict.fromkeys(refs))[:8]


def detect_mismatches(asset: Asset, grammar: Grammar) -> list[str]:
    out = []
    q = asset.quality or {}
    for issue in q.get("issues", []):
        out.append(f"quality: {issue}")
    folder = (asset.folder or "").lower()
    name = f"{asset.name} {asset.semantic} {' '.join(asset.tags)}".lower()
    if asset.kind == "logo":
        for cw in (grammar.logo_rules or {}).get("colorways", []) or []:
            bg = str(cw.get("bg", "")).lower()
            logo = str(cw.get("logo", "")).lower()
            if "dark" in folder and "light" in bg and "dark" not in name:
                out.append(f"logo colourway '{logo}' paired with '{bg}' bg per rules — check dark-mode folder fit")
            if "light" in folder and "dark" in bg and "white" in name:
                out.append("white logo stored under light folder may fail contrast rules")
    if "dark" in folder and "white" not in name and asset.kind == "logo" and "dark" not in name:
        out.append("non-white logo under dark-mode class may violate colourway rules")
    if asset.exact_required and not asset.png:
        out.append("exact-required asset has no raster")
    for r in grammar.context_rules:
        then = (r.then or "").lower()
        if any(w in then for w in ("never", "avoid", "don't", "do not")):
            tokens = [t for t in re.split(r"\W+", (r.when or "").lower()) if len(t) > 2]
            if tokens and any(t in name or t in folder for t in tokens):
                out.append(f"rule '{r.name}': {r.then}")
    return list(dict.fromkeys(out))[:8]


def enrich(asset: Asset, grammar: Grammar) -> Asset:
    asset.colors = asset.colors or dominant_colors(asset.png)
    asset.use_cases = use_cases_for(asset)
    asset.rule_refs = rule_refs_for(asset, grammar)
    asset.mismatches = detect_mismatches(asset, grammar)
    return asset
