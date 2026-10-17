# Architecture

## Design thesis

The brief ranks **output quality first**. Image models alone drift — wrong fonts,
redrawn logos, whole-canvas changes on a "small" edit. So the system splits:

- **Models propose** (creative composition, copy, visual judgement, pixels).
- **Code enforces** (brand fidelity, exact assets, pixel-intact edits, measurable output).

## Pipeline

```
Brand kit ─ingest─▶ catalog (90 assets: quality/colour/use-case/mismatch/rules)
                    grammar (colours, typography, recipes, lexicon, techniques)
                    fonts (per-page typeface identification)
                         │
use case ─▶ idea cohorts (DeepSeek-V4-Pro, folder-scoped) ─▶ N briefs
            each: story, idea, colour story, copy block, explicit asset set, zone map
                         │            parallel ThreadPoolExecutor
             compose v1…vn (GPT Image + raw asset refs + contact sheet)
                         │
             judge/fix loop (DeepSeek-V4.1-Flash vision + NCC asset match)
             7 checks · score = pass ratio · early-stop on stagnation · max 3 fixes
                         ▼
                    winner selection (best score)
                         ▼
        replacement plan → measure ink (vision windows + CV) → masked strip
        (+ composite-back) → verify strip → layered manifest → Konva canvas
                         ▼
        classify_edit → text (layer patch) | visual (raster repaint) | both
        draft chain: generated → edit-1 → edit-2 …   (old jobs stay editable)
```

## Model split (strict)

| Model | Role | Notes |
|-------|------|-------|
| DeepSeek-V4-Pro (Azure, text-only thinking) | cohort planning, copy, edit classification | rejects `image_url` — never send pixels |
| DeepSeek-V4.1-Flash (Azure, vision) | judge, strip verify, asset naming, element windows | typed content parts |
| GPT Image (OpenAI) | all pixel work: generate, fix, masked strip, visual edits | rejects SVG → `imutil.ensure_raster` (cairosvg → qlmanage fallback) |

## The replacement policy (fidelity core)

Implemented in `backend/app/fidelity/textfit.py` + `backend/app/ingest/fonts.py`:

1. **Plan** (`replacement_plan`) — per element:
   text is replaceable **only** if the corresponding brand font file exists
   (metric-similar fallbacks don't count); logo **only** if an exact-wordmark brand
   asset exists. Everything else is marked `replace: false`.
2. **Measure** (`measure_overlays`) — DeepSeek Flash proposes coarse element windows
   (normalized `[x0,y0,x1,y1]`); deterministic CV (`measure_ink`, `cta_pill_metrics`)
   tightens to exact ink bbox, stroke colour, fitted font size.
3. **Strip** (`strip_text_and_logo`) — masked `images.edit` scoped **only** to
   replaceable elements (mask + prompt skip kept-baked ones; removal prompt lists
   exact strings/regions).
4. **Composite-back** (`_composite_edit`) — the model drifts whole-canvas even with a
   perfect mask, so code re-composites the original everywhere outside the masked
   windows (2px feather). Outside-strip drift measured **29.4% → 0.04%**.
5. **Manifest** (`fidelity/manifest.py`) — layers: locked design raster + replaceable
   image/text layers. Logo lands on its measured ink box (`fit_asset_box` padding
   compensation — not brittle NCC); decorative slots NCC-match back with bbox
   plausibility + zone fallback. Non-replaced elements simply have no layer —
   they live in the raster, untouched.
6. **Verify** (`judge/critic.py::verify_strip`) — vision pass confirms removed
   elements are gone; kept-baked zones are exempt; leftovers trigger up to 3 re-strips.

Validated end-to-end by `workspace/probe/validate_policy.py` (7/7 checks —
pixel-intact proof + measured placement + plan correctness).

## Edit semantics

`edits.py::classify_edit` (thinking model, sees the manifest):

| Kind | Effect |
|------|--------|
| `text` | patch layer content in the manifest — instant, pixel-exact (font loaded via FontFace in the canvas) |
| `visual` | masked repaint of the design raster only — prompt **forbids text/logos**, live layers stay exact |
| `both` | both of the above |

Drafts chain via `parent` (`generated`, `edit-1`, …). `_ensure_generated` backfills a
`generated` root for jobs created before the draft system — previous jobs stay editable.

## Judging (the 7 checks)

`judge/critic.py` — copy fidelity · text-free cleanliness · asset identity · brand
rules · technique · artifacts · composition, plus per-slot NCC template match
(`fidelity/match.py`) against the exact brand artwork. Score = pass ratio. Fix
prompts must quote exact strings/regions (`_harden_fix`); the loop early-stops on
score stagnation and skips a final throwaway fix.

## Module map

```
backend/app/
  flow.py               orchestration: plan → compose → judge → select → strip → manifest
  llm.py                chat_text (pro/flash), chat_vision (flash), generate_image, edit_image(mask)
  edits.py              edit classification + text/visual draft application
  main.py               FastAPI routes
  store.py              brand CRUD, catalog query, folder tree, job persistence
  brief/cohorts.py      pro-thinking idea cohort planner
  compose/composer.py   compose/fix/strip + mask building + composite-back
  compose/prompts.py    all image prompts (palette-only, logo colourways, no-mush rules)
  judge/critic.py       judge, verify_strip, verify_fidelity
  judge/layout_tune.py  vision placement fallback
  fidelity/textfit.py   replacement policy + ink/font measurement
  fidelity/match.py     NCC asset match (threshold + bbox plausibility)
  fidelity/manifest.py  layered manifest builder + exact asset paste
  ingest/pipeline.py    brand kit ingestion + indexing
  ingest/quality.py     quality/colour/use-case/mismatch enrichment
  ingest/verify.py      brand-rule extraction
  ingest/fonts.py       font identification + font file resolution
  imutil.py             SVG → PNG (cairosvg → qlmanage)
frontend/src/
  pages/                Brands · BrandHome (assets) · Jobs · Create · Job (trail) · Edit
  components/           CanvasEditor (Konva) · VariantGallery · TrailPanel · JudgeDiffPanel
  api.js                REST client + workspace file URLs
```

## Known constraints

- DeepSeek-V4-Pro is **text-only** — vision always routes through Flash.
- OpenAI images API **rejects SVG** — everything rasterized first.
- Text layers appear only when the brand font is resolvable; otherwise the design
  keeps its baked text intact (policy, not a bug — see `textfit.have_corresponding_font`).
- Sizes: generated images 1024² (GPT Image); boxes normalized `[x0,y0,x1,y1]` internally.
