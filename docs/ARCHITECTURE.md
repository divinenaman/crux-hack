# Architecture

## Design thesis

The brief ranks **output quality first**. The old approach (image model paints
everything → strip text/logo out → paste layers back) fights constant drift:
garbled text, redrawn logos, whole-canvas changes, lossy strip. So the pipeline is
**layout-first**:

- **Models propose** (creative layout, copy, background scene, visual judgement).
- **Code enforces** (exact text/asset placement, colour contracts, separation).

The image model's only job is the background in the blank space. Text and brand
elements never enter it — divergence is not repaired, it is **impossible**.

## Pipeline

```
Brand kit ─ingest─▶ catalog (element|reference · colourway groups · palette refs)
                    grammar (colours, typography, recipes, lexicon, techniques)
                    fonts (per-page typeface identification)
                         │
use case ─▶ idea cohorts (thinking model, folder-scoped) ─▶ N layout specs
            each: copy + font colours, placements (text/image/shape with rects),
                  bg_fields (colour-control contract), bg_story, palette_refs
                         │            parallel ThreadPoolExecutor
        layout proof render (real font text + exact PNGs + shapes on flat fields)
                         │
        judge (det: bounds/overlap/fit/contrast/clearspace + vision: hierarchy/
        balance/alignment/brand feel) ─▶ perfect loop (model adjusts spec) ×2
                         ▼
        keep-out silhouettes ─▶ masked inpaint (white = repaint, black = never touch)
        prompt = bg_story + per-field colour control + palette + NO text/logos/people
                         ▼
        hole fill (silhouette regions → ring-median) → complete background raster
                         ▼
        contrast enforcement: measure ACTUAL painted bg under each text block,
        flip font colour if a field was missed (text has only its font colour)
                         ▼
        composite preview (code) + fill judge (no baked text? fields honoured?)
                         ▼
        winner ─▶ manifest = background raster + shape + image + text layers
                         ▼
        classify_edit → text | visual | assets | layout | both
        draft chain: generated → edit-1 → edit-2 …   (old jobs stay editable)
```

## Model split (strict)

| Model | Role | Notes |
|-------|------|-------|
| LiteLLM `open-fast` (text+vision) | layout specs, copy, edit classification | |
| LiteLLM `kimi-latest` (spatial) | layout proof critique, fill judge, asset bbox tighten | typed content parts |
| Cloudflare `flux-1-schnell` + `sd1.5-inpainting` | ALL pixel work: background fill, visual edits | rejects SVG → `imutil.ensure_raster` |

## The layout-first contract (fidelity core)

1. **Classify** (`ingest/groups.py`) — every asset is `element` (placeable: logo,
   charm, icon, shape, UI card) or `reference` (full image/scene → inspiration +
   palette examples, never placed). Colourway variants of one element share a
   `colorway_group` ("Xero Logo - White/Navy/Light Blue" → `logo_xero`).
2. **Plan** (`brief/fastplan.py` + `brief/placements.py`) — placements with exact
   copy + font colours + element ids (colourway-coordinated: light elements on
   dark fields) + shapes + `bg_fields`: per-region colour control. `coordinate()`
   enforces WCAG ≥4.5:1 between every font colour and the field (or shape fill)
   under it — **text has no box behind it, only font colour**, so the field must
   carry the contrast.
3. **Layout** (`layout/canvas.py`, `layout/judge.py`) — the proof renders the REAL
   design (brand font, exact PNGs, shape fills) on the flat field colours. Det
   checks + vision critique; the reasoning model perfects rects/colourways/fields
   BEFORE any pixel is generated (cheap loop).
4. **Fill** (`compose/fill.py`) — keep-out silhouettes (black on white) + mask
   (alpha 255 = keep silhouettes, 0 = repaint blank). Prompt = bg_story + colour
   control + palette + forbidden content list. `hole_fill` floods the silhouette
   regions from the surrounding scene so the background is complete (moving a
   layer later shows scene, not a hole).
5. **Contrast enforcement** (`measure_bg_contrast` + `enforce_contrast`) — sample
   the ACTUAL painted bg under each text block; if the model missed a field the
   font colour flips to the best-contrast alternative (honest, deterministic).
6. **Manifest** (`fidelity/manifest.py`) — separation by construction: layer 0 =
   background raster, then shape/image/text layers at their planned px boxes
   (text pre-fitted with real font metrics — what the proof judged).

Validated end-to-end by the dry-run in `docs/TESTING.md` (layout det checks 6/6,
contrast contract, manifest/preview/edit chain).

## Edit semantics

`edits.py::classify_edit` (thinking model, sees every layer):

| Kind | Effect |
|------|--------|
| `text` | patch layer content — instant, pixel-exact (font via FontFace in the canvas) |
| `visual` | masked repaint of the BACKGROUND raster only — prompt forbids text/logos; live layers untouched (they aren't in the raster) |
| `assets` | RAG-retrieve catalog elements and add image layers (background stays clean) |
| `layout` | move/resize layers (a CTA pill rides with its label via role pairing) |
| `both` | text + visual |

Drafts chain via `parent` (`generated`, `edit-1`, …). `ensure_finalized` backfills
a `generated` root for jobs created before the draft system.

## Judging

- **Layout judge** (`layout/judge.py`): det — bounds · text separation · piece
  clearance (CTA pill under its label is legal) · copy fit · contrast contract ·
  logo clearspace. Vision — hierarchy · balance · alignment · brand feel · crowding.
  Score = weighted pass ratio; perfect loop early-stops at ≥90.
- **Fill judge** (`compose/fill.py::judge_fill`): no_text · no_logo · field_colors
  · artifacts · story_fit · smooth_edges on the bare background.

## Module map

```
backend/app/
  flow.py               orchestration: plan → layout → perfect → fill → composite → manifest
  llm.py                chat_text, chat_vision, generate_image, edit_image(mask)
  edits.py              edit classification + text/visual/assets/layout draft application
  main.py               FastAPI routes
  store.py              brand CRUD, catalog query, folder tree, job persistence + classify migration
  brief/cohorts.py      deep-thinking idea cohort planner (zones bridged to placements)
  brief/fastplan.py     layout-first design planner (llm + deterministic fallback)
  brief/placements.py   placement spec: contrast math, colour coordination, sanitizers
  layout/canvas.py      proof / keepout / composite renderer (one drawing core)
  layout/judge.py       det + vision layout judge, perfect loop
  compose/fill.py       fill mask/base/prompt, masked inpaint, hole fill, contrast enforcement
  compose/prompts.py    size helpers + legacy bake prompts
  fidelity/manifest.py  layered manifest builder (bg + shape + image + text)
  fidelity/typo.py      font resolution + text fitting + asset ink boxes
  fidelity/render.py    manifest → flattened preview composite
  ingest/pipeline.py    brand kit ingestion + indexing
  ingest/classify.py   vision asset classification (element|reference + colorway)
  ingest/groups.py      colourway groups, palette refs, colour-coordinated picks
  ingest/quality.py     quality/colour/use-case/mismatch enrichment
  ingest/verify.py      brand-rule extraction
  ingest/fonts.py       font identification + font file resolution
  imutil.py             SVG → PNG (cairosvg → qlmanage)
  archive/              the old generate-then-strip path (wireframe/composer/critic/
                        layout_tune/textfit/match) — reference only, never imported
frontend/src/
  pages/                Brands · BrandHome (assets) · Jobs · Create · Job (trail) · Edit
  components/           CanvasEditor (Konva: raster/shape/image/text layers) · VariantGallery · TrailPanel · JudgeDiffPanel
  api.js                REST client + workspace file URLs
```

## Known constraints

- Cloudflare fill model is prompt-guided for colour control — when it misses a
  field the font colour flips (`enforce_contrast`); a targeted re-inpaint is the
  planned hardening.
- Text layers use the brand font when a real font file resolves; otherwise the
  fallback face (metric-similar) — `typo.resolve_font_path`.
- Sizes: fill canvases 1024²-class per ratio (`prompts.size_for`); boxes normalized
  `[x,y,w,h]` fractions in specs, px `[x,y,w,h]` in manifest layers.
- The archived generate-then-strip path lives under `app/archive/` for reference
  (re-skin of pre-existing flat designs is out of scope for the layout-first path).
