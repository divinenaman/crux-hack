# Demo Script — Agentic Image Editor (Crux-2)

Presenter notes for the GetCrux hackathon walkthrough (~7 min).
Judging priority: **output quality > code understanding/system design > speed/features > UI/UX > presentation.**

> Pipeline is **layout-first**: the canvas is laid out with real text/elements/shapes
> (contrast-judged before any pixels); the image model only paints the **whole
> background scene** around the pieces (colour-controlled fields, no text/logos).
> Text/asset divergence is impossible by construction — they never enter the image
> model as content. Details + diagrams: docs/ARCHITECTURE.md.

---

## 1. Live demo flow (5 min)

Open http://localhost:5173 (backend on :8000).

| # | Screen | What to show | Say |
|---|--------|--------------|-----|
| 1 | `/` | Brand card — 90 assets, N jobs | "One brand kit ingested: 90 assets, 6 recipes, 11 context rules, 12 lexicon shapes." |
| 2 | `/b/xero` | Folder tree (6 asset classes) + query filters | "Asset-class folders with quality/colour/use-case/mismatch indexing; colourway groups (white/navy logo variants collapse onto one element)." |
| 3 | `/b/xero/new` | Use case `Get a Xero Coach — Get ahead on your bookkeeping`, ratio 1:1, folder scope `22_Charms` | "Folder-scoped generation: the planning agent only sees the charm asset class." |
| 4 | `/b/xero/j/{jid}` | Progressive trail: `brief → contact → layout → compose → select → manifest` | "Every stage is inspectable. N composition archetypes run in parallel; the wireframe is judged before pixels; the composite is judged after the fill." |
| 5 | Variant gallery | Variants + stage notes | "Layouts come from six composition archetypes — each with one mandatory rule-break (bleed, overlap, or a tilted piece). Scores are honest; the trail is an audit log." |
| 6 | `/b/xero/j/{jid}/e/generated` | Konva canvas: background raster + live shape/image/text layers | "The winner **is** the layered canvas — separation by construction. Nothing was ever baked and stripped back out." |
| 7 | Canvas edit — text | Instruction: `Change the headline to "Books done. Life on."` | "Typed layer op — instant layer update in the brand font, zero image work." |
| 8 | Canvas edit — visual | Instruction: `Make the background warmer, softer blooms` | "`change_background` repaints the background raster only — the updated layers go out as a black-ink wireframe + colour fields, and the live pieces stay exact." |
| 9 | Draft chain | `generated → edit-1 → edit-2` selector | "Every edit is a linked draft (`parent` chain) — non-destructive, switchable." |

Fallbacks if a live run is mid-flight: any finished job on the jobs panel — each
ships the staged trail, the copyable fill prompt, and an editable manifest.

---

## 2. Output-quality talking points (heaviest criterion)

- **Separation by construction** — text and brand elements are placed by code,
  the image model paints only the background scene; the manifest layers ARE the
  pieces. Garbled model text is impossible: the model never draws text.
- **Creative composition doctrine** — six archetypes (`diagonal_tension`,
  `editorial_rag`, `poster_center`, `collage_scatter`, `split_world`,
  `negative_space_hero`) with scale drama, designed eye-path, a pool of calm, and
  ONE mandatory rule-break per design (edge bleed / overlap / tilt −14..14°
  clockwise around the piece centre — never on text).
- **Colour coordination enforced three times** — planning (`coordinate()`, WCAG
  ≥4.5:1 per field), pre-fill (`judge_wireframe`, deterministic), post-fill
  (`judge_readability`, vision: palette-coordinated remedies with a `bg_tone`
  guard so a vision misread can never put white on cream or navy on night).
- **Paint semantics are code, not vibes** — `"none"`/`transparent` mean NO paint
  (hollow accent rings stay hollow — the classic black-blob bug is impossible),
  tilts render centre-pivoted in both PIL and Konva, LLM style values coerce
  tolerantly (`"bold"` → 700) so a creative response can't crash a render.
- **Honest degradation** — free fill tier 429s or garbles? Flat-field fallback
  paints the colour contract exactly (guaranteed readable), and the fill prompt is
  shown in the studio — copy it into a stronger image model for production scenes.

---

## 3. Architecture walkthrough (2 min)

```
Brand kit ─ingest─▶ catalog (element|reference, colourway groups) + grammar + fonts
                        │
use case ─▶ composition archetypes (LLM T=0.85) ─▶ N layout specs
            copy + font colours + placements + bg colour fields
                        │            parallel ThreadPoolExecutor
        wireframe proof (black-ink text ref, real pieces) ─ judge_wireframe (det)
                        │
        fill: model paints the whole scene + clean colour fields (no text/logos)
                        │            (flat-field fallback on failure)
        composite (live pieces on top) ─ judge_readability (vision + bg_tone)
                        │
        winner ─▶ manifest (bg raster + shape + image + text layers)
                        │
        Konva canvas + classify_edit (agent + read_asset) ─▶ 9 ops (draft chain)
```

**Model split (strict):**

| Model | Role |
|-------|------|
| LiteLLM `open-fast` (text; `pro` alias) | archetypes, copy, design specs (T=0.85), edit classification |
| LiteLLM `kimi-latest` (vision) | post-fill readability judge (palette + `bg_tone` guard) |
| Cloudflare Workers AI (wireframe-reference fill + `sd1.5-inpainting`) | the ONLY pixel work — background fills + masked repaints (`IMAGE_MODEL` fallback) |

**Why this design:** model creativity inside deterministic guardrails. The planner
proposes bolder and bolder compositions; code enforces placement, paint semantics,
contrast contracts and separation. Full diagrams (system overview, pipeline,
readability chain) in `docs/ARCHITECTURE.md`.

Key files: `backend/app/flow.py` (orchestration), `brief/fastplan.py` (archetypes),
`edits.py` (judges + edit ops), `fidelity/manifest.py` (layers),
`frontend/src/components/CanvasEditor.jsx` (Konva).

---

## 4. Constraints worth mentioning (shows depth)

- Free fill model sometimes echoes the wireframe's black-ink glyphs as background
  "art" — live text is pasted and judged regardless; prompts are copyable to
  stronger models (supported workflow).
- Cloudflare rejects prompts > 2048 chars — fill prompts are budgeted.
- Cloudflare rejects SVG — `imutil.ensure_raster` (cairosvg → qlmanage fallback).
- Brand-scoped storage (`workspace/brands/{id}/…`); job state in `jobs/{id}.json`,
  artifacts in the sibling `jobs/{id}/` directory; run-state is race-guarded so a
  mid-run read can never clobber the trail.

---

## 5. Backup talking points

- Parallel variant generation (ThreadPoolExecutor — the trail updates per variant
  as it lands).
- Failure containment: contact sheet, fill, and the readability judge each degrade
  their stage (skip / flat fields / no remedies) — the variant still ships.
- Text edits cost zero image work (typed layer ops on the manifest).
- `job.log` + `job.trail` double as an audit log of every judgement and remedy.
