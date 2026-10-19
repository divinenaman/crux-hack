# Setup

Prerequisites: **Python 3.11+**, **Node 20+**, and API keys below. macOS/Linux.

## 1. API keys

Create `backend/.env` (never commit this file):

```bash
LITELLM_KEY=<litellm gateway key>   # planning/copy + all vision calls (LLM_MODEL=open-fast)
CF_ACCOUNT_ID=<cloudflare account>  # pixel work: flux-1-schnell generate + sd1.5-inpainting edits
CF_KEY=<cloudflare api token>
```

Optional overrides (defaults work for the hackathon endpoints):

```bash
DEEPSEEK_PRO_BASE=https://crux-hackathon-swe.openai.azure.com/openai/v1/
DEEPSEEK_FLASH_BASE=https://crux-hackathon-eus2.openai.azure.com/openai/v1/
DEEPSEEK_PRO_MODEL=DeepSeek-V4-Pro
DEEPSEEK_FLASH_MODEL=DeepSeek-V4.1-Flash
IMAGE_MODEL=gpt-image-2
WORKSPACE_DIR=./workspace
```

## 2. Backend (port 8000)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
nohup .venv/bin/python ../workspace/serve.py > /tmp/crux-server.log 2>&1 &
curl http://127.0.0.1:8000/api/health   # → {"ok":true, ...}
```

`workspace/serve.py` is cwd-safe — run it from anywhere.

## 3. Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173  (proxies /api and /files to :8000)
```

Production build (optional): `npm run build && npm run preview`.

## 4. Brand data

Brand kit images are **not shipped** in the repo (licensed artwork). Drop any kit on disk and ingest it — the Xero kit works out of the box:

```bash
# point ingest at your kit folder (pngs/svgs, any folder depth = asset classes)
curl -X POST http://127.0.0.1:8000/api/brands/xero/ingest \
  -H 'content-type: application/json' -d '{"root": "/path/to/Brand Kit"}'
# or click "Re-ingest / index assets" in the UI sidebar (root defaults to workspace/assets)
```

Copy kit images into `workspace/assets/` first if you want the default root. Ingestion builds
`workspace/brands/{id}/catalog.json` (indexed: quality/colour/use-case/mismatch/rules),
`grammar/grammar.json` (colours, typography, recipes, lexicon, techniques) and identifies fonts.

Any brand works: `POST /api/brands {id, name}` then `POST /api/brands/{id}/ingest {root: "<path to kit>"}`.

## Optional system deps

- `cairosvg` (pip, in requirements) — SVG → PNG conversion for the OpenAI images API
  (which rejects SVG). Falls back to macOS `qlmanage` if unavailable.
- `playwright` — only for the E2E UI checks; not required to run.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `import app` fails when starting manually | run `workspace/serve.py` (sets `sys.path`), or `cd backend` first |
| Image 422 from OpenAI | an asset is SVG — `imutil.ensure_raster` handles it; make sure cairosvg installed |
| Vision call 400 on DeepSeek-Pro | Pro is text-only — vision must go through Flash |
| Port 8000 busy | `lsof -ti:8000 \| xargs kill` or edit `workspace/serve.py` |
| Fonts fallback to Figtree | expected — brand fonts resolve from `workspace/fonts/` + system fonts |
