# Crux — Agentic Image Editor

**GetCrux hackathon entry** — turns a *brand kit + use case* into judged ad variants and an
**editable layered canvas**, with an agent loop that plans → composes → judges → fixes →
strips to live layers → hands over to a Konva editor.

Judging priority (per brief): **output quality > code understanding / system design > speed & features > UI/UX > presentation.**
The architecture below is built around that order — a strict vision judge and
deterministic brand-fidelity code first, features second.

---

## Quick start (3 commands)

```bash
# 1. backend  (Python 3.11+, keys in backend/.env — see docs/SETUP.md)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "DEEPSEEK_PRO_KEY=...  DEEPSEEK_FLASH_KEY=...  OPENAI_IMAGE_KEY=..." > .env
nohup .venv/bin/python ../workspace/serve.py > /tmp/crux-server.log 2>&1 &

# 2. frontend (Node 20+)
cd frontend && npm install && npm run dev

# 3. open → http://localhost:5173  (ingest any brand kit — see docs/SETUP.md §4; images not shipped)
```

Full setup, API keys, and troubleshooting: **[docs/SETUP.md](docs/SETUP.md)**.
Judge walkthrough (10 min script): **[docs/USAGE.md](docs/USAGE.md)**.
Architecture & design decisions: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
View test report (41/41 checks): **[docs/TESTING.md](docs/TESTING.md)**.

---

## What it does

1. **Ingest** a brand kit (Xero: 90 assets, 6 asset classes) → indexed catalog with
   quality / colour / use-case / mismatch / brand-rule metadata + extracted grammar
   (colours, typography, recipes, lexicon, techniques) + font identification.
2. **Plan** 3 distinct idea cohorts (thinking model) — story, copy, explicit asset set,
   zone map, folder-scoped.
3. **Compose** variants in parallel (GPT Image + raw asset refs + contact sheet).
4. **Judge → fix** loop (vision judge, 7 checks + per-asset NCC template match, score =
   honest pass ratio, early-stop on stagnation).
5. **Deliver** the winner as a layered manifest: design raster + replaceable logo/text
   layers — with a **deterministic replacement policy** (see below).
6. **Edit** forever: instruction box classifies each edit as `text` (instant layer
   update) / `visual` (masked repaint of the raster only) / `both`, chaining drafts
   (`generated → edit-1 → edit-2 …`). Previous jobs stay editable.

### The fidelity guarantee (why the output looks like the brand)

| Rule | Enforcement |
|------|-------------|
| Text is replaced with a live layer **only** if the brand's exact font is available | `fidelity/textfit.py::have_corresponding_font` — otherwise text stays baked, design intact |
| Logo is replaced **only** with a matching brand asset (exact wordmark) | `_pick_logo_asset` + paste at measured ink box |
| Everything outside removed elements is **pixel-identical** | masked `images.edit` output composited back through the mask in code (`composer._composite_edit`) — model drift 29.4% → 0.04% |
| Brand colours / logo colourways / safe zones | palette-only prompts, grammar-derived pairs, mismatch-aware asset shortlists |

Models propose; **code enforces**.

---

## Architecture (short)

```
Brand kit ─ingest─▶ catalog + grammar + fonts
                       │
prompt ─▶ idea cohorts (DeepSeek-V4-Pro) ─▶ 3 briefs (copy, slots, zones)
                       │        parallel
        compose v1/v2/v3 (GPT Image + asset refs)
                       │
        judge/fix loops (DeepSeek-V4.1-Flash vision + NCC)
                       │
        winner ─▶ replacement plan ─▶ measure ink ─▶ masked strip (+ composite-back)
                       │
        manifest (design raster + replaceable layers only)
                       │
        Konva canvas ─ classify_edit ─▶ text | visual | both  (draft chain)
```

| Model | Role |
|-------|------|
| DeepSeek-V4-Pro (text-only thinking) | cohorts, copy, edit classification |
| DeepSeek-V4.1-Flash (vision) | judge, strip verify, asset naming, element windows |
| GPT Image | all pixel work — generate, fix, masked strip, visual edits |

Details + module map + constraints: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Repo layout

```
backend/app/           FastAPI app — flow.py orchestrates the pipeline
  brief/               idea cohort planner (thinking model)
  compose/             prompts + compose/fix/strip + mask building
  judge/               vision judge, strip verify, fix hardening
  fidelity/            textfit (replacement policy), NCC match, manifest builder
  ingest/              brand kit pipeline, quality indexing, fonts
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
