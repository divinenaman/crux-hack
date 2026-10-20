# Crux — Agentic Image Editor

**GetCrux hackathon entry** — turns a *brand kit + use case* into judged ad variants and an
**editable layered canvas**, with a **layout-first** pipeline: the reasoning model places
real text/elements/shapes on a blank canvas (positioned → judged → perfected), the image
model only paints the background in the blank space (colour-controlled), and the two are
composited in code — **background separable from every element on top**.

Judging priority (per brief): **output quality > code understanding / system design > speed & features > UI/UX > presentation.**
The architecture below is built around that order — a strict layout judge and
deterministic colour-contract code first, features second.

---

## Quick start (3 commands)

```bash
# 1. backend  (Python 3.11+, keys in backend/.env — see docs/SETUP.md)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "LITELLM_KEY=...  CF_ACCOUNT_ID=...  CF_KEY=..." > .env
nohup .venv/bin/python ../workspace/serve.py > /tmp/crux-server.log 2>&1 &

# 2. frontend (Node 20+)
cd frontend && npm install && npm run dev

# 3. open → http://localhost:5173  (ingest any brand kit — see docs/SETUP.md §4; images not shipped)
```

Full setup, API keys, and troubleshooting: **[docs/SETUP.md](docs/SETUP.md)**.
Judge walkthrough (10 min script): **[docs/USAGE.md](docs/USAGE.md)**.
Architecture & design decisions: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
Earlier pipeline test report: **[docs/TESTING.md](docs/TESTING.md)** (pre layout-first).

---

## What it does

1. **Ingest** a brand kit (Xero: 90 assets, 6 asset classes) → indexed catalog with
   quality / colour / use-case / mismatch / brand-rule metadata + extracted grammar
   (colours, typography, recipes, lexicon, techniques) + font identification — and
   **layout-first classification**: every asset is an `element` (placeable: logos,
   charms, icons, shapes, UI cards — often in several **colourways** grouped together)
   or a `reference` (full images/scenes → inspiration + palette examples only).
2. **Plan** 3 distinct idea cohorts (thinking model) as **layout specs**: exact copy +
   font colours, placed elements (colourway-coordinated), shapes, and **bg colour
   fields** — the contrast contract for the background (text has no box behind it,
   only font colour, so the painted field must carry the contrast).
3. **Wireframe: positioned → judged** — code renders the wireframe proof (real brand
   font text as black ink, exact element PNGs, designed shapes) and a deterministic
   judge enforces the contrast contract (label vs its container, text vs its colour
   field) **before any pixels are generated**. Creative layouts come from six
   composition archetypes, each with one mandatory rule-break (bleed / overlap /
   tilted piece).
4. **Fill** — the image model paints the **whole scene around the pieces** from the
   wireframe reference, leaving clean flat colour fields under every text block
   (prompt carries the scene story + per-field hexes + palette and *forbids* any
   text/logos/UI). On API failure the fields fall back to exact flat colours.
5. **Composite + judge** — pieces are pasted on top in code and a vision judge
   checks what the eye actually sees: unreadable pieces get the smallest remedy
   (ink/container recolour — palette-coordinated, tone-guarded; never a second
   fill), synced back and re-composited.
6. **Deliver** the winner manifest instantly — **separation by construction**:
   background raster + shape layers + image layers + text layers. Nothing was ever
   baked and stripped back out. **Edit** forever: text edits patch layers instantly,
   visual edits repaint the background only, asset-adds place catalog elements,
   instructions can move/resize layers (CTA pill rides with its label). Previous jobs
   stay editable.

### The fidelity guarantee (why the output looks like the brand)

| Rule | Enforcement |
|------|-------------|
| Text is **always** exact live layers in the brand font (garbled model text is impossible — the model never draws text) | `layout/canvas.py` + `fidelity/manifest.py` — placed at planned rects, fitted with real font metrics |
| Logo/elements are **exact brand assets** (colourway-coordinated with their field) | `ingest/groups.py` colourway groups + `brief/placements.py::coordinate` |
| Text readability — text has only a font colour, so the bg field must carry contrast | planned: `coordinate()` (≥4.5:1 per field) · pre-fill: `judge_wireframe` (det) · after fill: `judge_readability` (vision, `bg_tone` guard + brand palette) flips ink or container |
| Background is separable from every element | fill paints blank space only (keep-out mask) · pieces composited on top in code · manifest layers ARE the pieces |

Models propose; **code enforces**.

---

## Architecture (short)

```
Brand kit ─ingest─▶ catalog (element|reference, colourway groups) + grammar + fonts
                       │
prompt ─▶ composition archetypes (LLM T=0.85; 6 styles + rule-break doctrine)
                       │        fallback: 3 deterministic skeletons
       N layout specs (copy, placements, bg fields) ── parallel variants
                       │
       wireframe proof (black-ink ref + real pieces) ─ judge_wireframe (det)
                       │
       fill: model paints the WHOLE scene + clean colour fields (no text/logos)
                       │        (flat-field fallback on API failure)
       composite (live pieces on top) ─ judge_readability (vision + bg_tone guard)
                       │
       winner ─▶ manifest (bg raster + shape + image + text layers)
                       │
       Konva canvas ─ classify_edit (agent + read_asset) ─▶ 9 ops (draft chain)
```

| Model | Role |
|-------|------|
| LiteLLM gateway — `open-fast` (default text; `pro` alias) | archetypes, copy, design specs (T=0.85), edit classification |
| LiteLLM — `kimi-latest` (vision) | post-fill readability judge (palette + `bg_tone` guard) |
| Cloudflare Workers AI — wireframe-reference fill + `sd1.5-inpainting` | the ONLY pixel work — background fills + masked repaints (free tier; `IMAGE_MODEL` fallback) |

Details + module map + constraints: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Repo layout

```
backend/app/           FastAPI app — flow.py orchestrates the pipeline
  brief/               composition-archetype planner + placement/colour-contract helpers
  layout/              canvas renderer (wireframe proof/composite — tilt, none-paint) + optional perfect-loop judge
  compose/             fill.py (whole-scene background fill + colour fields) + prompts
  fidelity/            manifest builder, text fitting (typo, tolerant weights), preview composite
  ingest/              brand kit pipeline, quality indexing, fonts, element/reference groups
  archive/             the old generate-then-strip path (reference only, not imported)
frontend/src/          React + Konva canvas (pages, components)
workspace/             runtime data (brand kits under assets/ — not shipped; jobs under brands/)
  serve.py             backend entrypoint (cwd-safe)
docs/                  SETUP · USAGE · ARCHITECTURE
DEMO.md                live demo script
```

Import convention (backend): root modules use single-dot imports (`from .models`);
subpackages use double-dot (`from ..models`).

---

## API (for scripting the judge flow)

```
GET/POST  /api/brands
POST      /api/brands/{bid}/ingest            {root}
GET       /api/brands/{bid}/tree|assets|rules
GET/POST  /api/brands/{bid}/jobs              {use_case, ratio, variants, folder}
POST      /api/brands/{bid}/jobs/{jid}/run    {ratio?} — executes the pipeline
GET       /api/brands/{bid}/jobs/{jid}
GET       /api/brands/{bid}/jobs/{jid}/manifest?draft=generated|edit-N
POST      /api/brands/{bid}/jobs/{jid}/edits  {parent, instruction}
GET       /api/brands/{bid}/refs/{asset_id}
```

UI routes: `/` brands · `/b/:bid` assets · `/b/:bid/jobs` jobs panel ·
`/b/:bid/new` create · `/b/:bid/j/:jid` job trail + variants ·
`/b/:bid/j/:jid/e/:editId` editable canvas + instruction box.
