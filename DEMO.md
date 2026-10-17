# Demo Script — Agentic Image Editor (Crux-2)

Presenter notes for the GetCrux hackathon walkthrough (~7 min).  
Judging priority: **output quality > code understanding/system design > speed/features > UI/UX > presentation.**

---

## 1. Live demo flow (5 min)

Open http://localhost:5173 (backend on :8000).

| # | Screen | What to show | Say |
|---|--------|--------------|-----|
| 1 | `/` | Xero brand card — 90 assets, N jobs | "One brand kit ingested: 90 assets, 6 recipes, 11 context rules, 12 lexicon shapes." |
| 2 | `/b/xero` | Folder tree (6 asset classes: Charms, Blooms, Logos, Illustrations, UI refs, Templates) + query filters | "Asset-class folders with quality/colour/use-case/mismatch indexing. Every asset carries rules-derived mismatch checks." |
| 3 | `/b/xero/new` | Use case `Get a Xero Coach — Get ahead on your bookkeeping`, ratio 1:1, **folder scope `22_Charms`** | "Folder-scoped generation: the planning agent only sees the charm asset class." |
| 4 | `/b/xero/j/{jid}` | Progressive trail: `brief → contact → compose → judge → fix → variant → select → strip → tune → manifest` | "Every stage is inspectable. Three idea cohorts run in parallel; the judge loop fixes surgically and early-stops on stagnation." |
| 5 | Variant gallery | 3 variants with judge scores + notes | "Scores come from a strict 7-check critic + deterministic NCC asset match — not vibes." |
| 6 | `/b/xero/j/{jid}/e/generated` | Konva canvas: design raster + live logo/text layers | "The winner is stripped of baked text/logo via masked repaint, then rebuilt as editable layers." |
| 7 | Canvas edit — text | Instruction: `Change the headline to "Books done. Life on."` | "Classified as `text` — instant layer update, zero image work." |
| 8 | Canvas edit — visual | Instruction: `Make the background warmer, softer blooms` | "Classified as `visual` — masked repaint of the design raster only. The prompt forbids text/logos so the live layers stay exact." |
| 9 | Draft chain | `generated → edit-1 → edit-2` selector | "Every edit is a linked draft (`parent` chain) — non-destructive, switchable." |

Fallbacks if a live run is mid-flight: show the verified run `job_Get_a_Xero_Coach___Get_a_90_1792234298` (folder-scoped `22_Charms`, winner 66.7, draft chain `generated → edit-1 → edit-3`) or the earlier full-catalog run `job_Get_a_Xero_Coach__Get_ah_90_1792230534` (3 cohorts, 8-layer manifest).

---

## 2. Output-quality talking points (heaviest criterion)

- **Strict judge, honest scores** — 7 required checks (copy fidelity, text-free cleanliness, asset fidelity, brand rules, technique, artifacts, composition) + per-slot NCC template match. Score = pass ratio; no grade inflation.
- **Surgical fix loop** — fix prompts must quote exact strings/regions (hardened in `judge/_harden_fix`); early-stop on score stagnation; max 3 rounds.
- **Replaceable-only strip → live layers** — text is erased and rebuilt ONLY when the corresponding brand font is available; the logo ONLY when a matching brand asset exists. Everything else stays baked into the design raster — the design remains intact. Vision windows + deterministic CV measure exact ink bbox/colour/size first; the strip mask and prompt are scoped to the replaceable items only.
- **Pixel-identical by construction** — the image model drifts whole-canvas even with a perfect mask, so the edit is composited back through the mask in code (29.4% outside-strip drift → 0.04%). Replaced text re-renders with the identified brand font; the logo is pasted from the exact brand asset onto its measured ink box (`paste_exact` + padding compensation).
- **Brand fidelity is deterministic** — palette-only prompts, logo colourway pairs from grammar, safe zones, mismatch-aware asset shortlists. Models propose; code enforces.
- **Judging-polish pass applied** — explicit logo variant in compose prompts (e.g. `Xero Logo White`), pixel-perfect asset language, hierarchy/no-mush guidance, and logo exempted from transient-bake NCC (it is re-placed exactly after strip).

---

## 3. Architecture walkthrough (2 min)

```
Brand Kit ─ingest─▶ catalog (90 assets, folders, quality/use-case/mismatch/rules)
                         │
prompt ─▶ idea cohorts (DeepSeek-V4-Pro, folder-scoped) ─▶ 3 briefs (story, copy, slots, zones)
                         │
            ┌────────────┼────────────┐        parallel ThreadPoolExecutor
            ▼            ▼            ▼
        compose v1    compose v2   compose v3     (GPT Image + contact sheet + raw refs)
            │            │            │
        judge/fix    judge/fix    judge/fix      (DeepSeek-V4.1-Flash vision + NCC)
            └────────────┼────────────┘
                         ▼
              winner ─▶ replacement plan ─▶ measure ink ─▶ masked strip (+ composite-back) ─▶ verify strip
                         ▼
              manifest (design raster + replaceable layers only — e.g. logo; text stays baked unless its font matches)
                         ▼
              Konva canvas + classify_edit → text | visual | both   (draft chain)
```

**Model split (per brief, strict):**

| Model | Role |
|-------|------|
| DeepSeek-V4-Pro (text-only thinking) | cohorts, copy, edit classification |
| DeepSeek-V4.1-Flash (vision) | judge, strip verify, classify/name assets |
| GPT Image | all pixel work — generate, fix, masked strip, visual edits |

**Why this design:** model creativity inside deterministic guardrails. Ingestion indexes every asset against the extracted grammar (mismatches = colourway/contrast/rule conflicts) and identifies the brand fonts; the manifest reconstructor places logos on their measured ink boxes and NCC-matches decorative assets back with bbox plausibility + zone fallback, so the canvas is composed of real brand parts, not a flat PNG.

Key files: `backend/app/flow.py` (orchestration), `edits.py` (edit semantics), `judge/critic.py` (judge/strip verify), `fidelity/manifest.py` (layered manifest), `frontend/src/components/CanvasEditor.jsx` (Konva). Full map in `README.md`.

---

## 4. Constraints worth mentioning (shows depth)

- DeepSeek-V4-Pro rejects `image_url` — all vision routed through Flash; typed content parts everywhere.
- OpenAI images API rejects SVG — `imutil.ensure_raster` (cairosvg → qlmanage fallback).
- Brand-scoped storage (`workspace/brands/{id}/…`) with legacy auto-migration on startup.

---

## 5. Backup talking points

- Parallel variant generation (was ~10 sequential image calls).
- Judge early-stop + skip-fix-after-final-round keeps cost/time bounded.
- Edit classification keeps text edits at 0 image cost.
- Live E2E evidence in `workspace/brands/xero/jobs/` — trail JSONs double as an audit log.
