"""Catalog retrieval (RAG) — resolve a natural-language 'want' to brand assets."""
import re

from . import store


def retrieve(brand_id: str, query: str, k: int = 3, exclude: set[str] | None = None) -> list:
    """Token + phrase match over name/tags/semantic/usage/use_cases. Best-first."""
    exclude = exclude or set()
    q = (query or "").strip().lower()
    qt = set(re.findall(r"[a-z0-9]+", q))
    scored = []
    for a in store.load_catalog(brand_id):
        if a.id in exclude:
            continue
        hay = f"{a.id} {a.name} {a.kind} {' '.join(a.tags)} {a.semantic} {a.usage} {' '.join(a.use_cases)} {' '.join(a.role_hints)} {a.folder}".lower()
        ht = set(re.findall(r"[a-z0-9]+", hay))
        score = float(len(qt & ht))
        if q and q in hay:
            score += 3.0
        for tok in qt:
            if len(tok) > 3 and tok in hay:
                score += 1.0
        if score > 0:
            scored.append((score, a))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    return [a for _, a in scored[:k]]
