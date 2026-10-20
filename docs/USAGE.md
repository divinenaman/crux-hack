# Usage — judge walkthrough (~10 minutes)

> The pipeline is **layout-first**: the canvas is laid out with real text/elements
> (judged + perfected), then the image model fills only the blank background.
> The trail shows `layout → compose (fill) → judge → manifest`. See ARCHITECTURE.md.

Everything needs **no API knowledge** — it's all in the browser at http://localhost:5173.

## 0. The one-minute version

`jobs → open the seeded job → Edit → type an instruction` — that's the product:
an agent made a brand-faithful ad, and you can keep editing it as live layers.

## 1. Asset intelligence (1 min)

Open **`/b/xero`** (or click the `xero` brand on `/`).

- Left sidebar: **6 asset classes** (folder tree) — arbitrary-depth class folders
  (e.g. dark/light mode style). Click a class to filter.
- 90 assets, each indexed with colour swatches, semantic tags, use cases,
  brand-rule refs and **mismatch warnings** (e.g. "patio use ignores background" —
  colourway/contrast conflicts the judge will later enforce).
- Search by name / semantic / tags; filter by kind, colour, use case.

## 2. Create a job (1 min)

**`/b/xero/new`** (or "+ Create image").

- Use case: e.g. `Get a Xero Coach. Get ahead. — quirky coaching ad for small business owners`
- Pick aspect ratio (1:1, 4:5, 9:16, 16:9) and how many variants (3 is a good demo).
- Optionally scope to one asset class (folder) — e.g. `22_Charms` — for themed sets.
- **Generate variants** — a full job takes ~3–5 min (3 parallel variants ×
  compose → judge → fix).

## 3. Watch the agent think (2 min)

**`/b/xero/j/:jobId`** — the left sidebar streams a **progressive trail**:

`BRIEF → ASSETS → COMPOSE → JUDGE → FIX → OUTPUT → WINNER → STRIP → TUNE → CANVAS`

Each step shows its artifact (contact sheet, composed design, re-judged score) and
notes (which strings/regions the fix targeted). Scores are honest pass ratios —
no grade inflation. The variant gallery shows every variant with its judge score,
story and failed checks.

## 4. Edit it (4 min — the important part)

Click **Edit** on the jobs panel / job banner → `/b/xero/j/:jobId/e/generated`.

- **Left**: draft chain (`generated`, `edit-1`, …) + the instruction box.
- **Center**: layered canvas — design raster underneath, live text/logo layers above
  (drag them). Modes: `composite` / `ghost` / `layers`.
- **Right**: layer list, judge diff (idea cohort, expected copy, failing checks with
  the exact fix prompts sent to the model), trail.

Try these instructions one at a time:

| Instruction | Kind | What happens |
|-------------|------|--------------|
| `change headline to 'Books done. Life on.'` | text | instant layer update, pixel-exact brand font/colour |
| `make the background warmer, softer blooms` | visual | masked repaint of the **raster only** — live layers untouched (prompt forbids text/logos) |
| `change the cta to 'Get your coach'` | text | CTA layer updates on the baked pill |

Each edit appends a draft (`edit-1 ← generated`) — click any draft to branch/review.
**Old jobs stay editable**: reopen any previous job and edit it later.

## 5. Brand fidelity, verified (1 min)

Open the **diff** tab on the canvas: 7 checks (copy fidelity, text-free cleanliness,
asset identity, brand rules, technique, artifacts, composition) + per-asset NCC
template match of the exact brand artwork. Failing checks show the exact fix prompt
that was sent to the image model.

Ask: *"why is the text not editable here?"* — answer: the kit specifies no typeface
for that page, so per the replacement policy the text **stays baked** (design stays
intact) instead of being approximated with a wrong font. The logo, which does have an
exact brand asset, is a live layer.

## API-only smoke (optional)

```bash
curl -X POST localhost:8000/api/brands/xero/jobs \
  -H 'content-type: application/json' \
  -d '{"use_case":"Get a Xero Coach. Get ahead.","ratio":"1:1","variants":3}'
curl localhost:8000/api/brands/xero/jobs/<job_id>            # poll status → done
curl localhost:8000/api/brands/xero/jobs/<job_id>/manifest   # layered manifest
curl -X POST localhost:8000/api/brands/xero/jobs/<job_id>/edits \
  -H 'content-type: application/json' \
  -d '{"parent":"generated","instruction":"change headline to '\''Books done. Life on.'\''"}'
```
