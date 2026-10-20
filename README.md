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
3. **Layout: positioned → judged → perfected** — code renders the layout proof
   (real brand font text, exact element PNGs, designed shapes on the colour fields);
   det checks (overlap, fit, margins, WCAG contrast) + vision critique; the reasoning
   model nudges rects/colourways/colours until it passes. **No pixels generated yet.**
4. **Fill** — the blank space only: the layout's keep-out silhouettes go out with a
   masked inpaint (white = repaint) whose prompt carries the bg story + per-field
   colour control + palette and *forbids* text/logos/people. Holes under pieces are
   filled deterministically so the background is complete.
5. **Composite + judge** — pieces are pasted on top in code (preview) and the actual
   painted colours under each text block are measured; font colours flip if the fill
   missed a field. The fill itself is judged (no baked text, fields honoured).
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
| Text readability — text has only a font colour, so the bg field must carry contrast | planned: `coordinate()` (≥4.5:1 per field) · after fill: `measure_bg_contrast` + `enforce_contrast` flips the font if the model missed a field |
| Background is separable from every element | fill paints blank space only (keep-out mask) · pieces composited on top in code · manifest layers ARE the pieces |

Models propose; **code enforces**.

---

## Architecture (short)

```
Brand kit ─ingest─▶ catalog (element|reference, colourway groups) + grammar + fonts
                       │
prompt ─▶ idea cohorts (thinking model) ─▶ layout specs (copy, placements, bg fields)
                       │
        layout proof (real pieces on colour fields) ─ judge (det + vision) ─ perfect loop
                       │
        keep-out silhouettes ─▶ masked fill (colour-controlled, no text/logos)
                       │
        hole fill ─▶ contrast enforcement (measure actual bg under text)
                       │
        composite preview + fill judge ─▶ winner ─▶ manifest
                       │
        background raster + shape + image + text layers ─▶ Konva canvas
                       │
        classify_edit ─▶ text | visual | assets | layout | both  (draft chain)
```

| Model | Role |
|-------|------|
| LiteLLM gateway — `open-fast` (default text+vision) | cohorts/layout specs, edit classification |
| LiteLLM — `kimi-latest` (spatial) | layout proof critique, fill judge |
| Cloudflare Workers AI — `flux-1-schnell` + `sd1.5-inpainting` | the ONLY pixel work — background fill + visual edits (free tier) |

Details + module map + constraints: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Repo layout

```
backend/app/           FastAPI app — flow.py orchestrates the pipeline
  brief/               idea cohort planner + placement/colour-contract helpers
  layout/              canvas renderer (proof/keepout/composite) + layout judge/perfect loop
  compose/             fill.py (colour-controlled background fill) + prompts
  fidelity/            manifest builder, text fitting (typo), preview composite
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
GET       /api/brands/{bid}/jobs/{jid}
GET       /api/brands/{bid}/jobs/{jid}/manifest?draft=generated|edit-N
POST      /api/brands/{bid}/jobs/{jid}/edits  {parent, instruction}
GET       /api/brands/{bid}/refs/{asset_id}
```

UI routes: `/` brands · `/b/:bid` assets · `/b/:bid/jobs` jobs panel ·
`/b/:bid/new` create · `/b/:bid/j/:jid` job trail + variants ·
`/b/:bid/j/:jid/e/:editId` editable canvas + instruction box.
