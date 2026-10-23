# Usage — judge walkthrough (~10 minutes)

> The pipeline is **layout-first**: the canvas is laid out with real text/elements
> (contrast-judged before any pixels), then the image model paints the whole
> background scene around the pieces (colour-controlled fields).
> The trail shows `brief → contact → layout → compose → select → manifest`.
> See ARCHITECTURE.md.

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
- **Generate variants** — a full job takes ~1–3 min (N parallel variants:
  plan → wireframe → fill → readability judge).

## 3. Watch the agent think (2 min)

**`/b/xero/j/:jobId`** — the left sidebar streams a **progressive trail**:

`BRIEF → CONTACT → LAYOUT → COMPOSE → SELECT → MANIFEST`

Each step shows its artifact (contact sheet, transparent full-layout reference, filled composite)
and notes (contrast remedies, readability flags with their fixes). The variant
gallery shows every final composite with its stage notes.

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
| `make the background warmer, softer blooms` | visual | `change_background` repaints the **background raster only** (layers go out as a wireframe + colour fields) — live pieces untouched |
| `change the cta to 'Get your coach'` | text | CTA label updates on its live pill layer (the pill rides along with the label on moves) |

Each edit appends a draft (`edit-1 ← generated`) — click any draft to branch/review.
**Old jobs stay editable**: reopen any previous job and edit it later.

## 5. Brand fidelity, verified (1 min)

Every glyph and brand element is a **live layer** — the image model receives their
reference pixels for coordination, but the final text and assets are composited
from the live layers in code. Readability is enforced in code at
three checkpoints: planned contrast (`coordinate`, ≥4.5:1 per field), a
deterministic pre-fill judge (`judge_wireframe`), and a post-fill vision judge
(`judge_readability`) whose remedies are palette-coordinated and tone-guarded
(`bg_tone`) — synced back into the brief and re-composited.

The image model may still echo details from its transparent reference in the
background; the exact live text and assets are composited on top afterward. The
reference and prompt used for each variant are visible in the Studio panel.

## API-only smoke (optional)

```bash
curl -X POST localhost:8000/api/brands/xero/jobs \
  -H 'content-type: application/json' \
  -d '{"use_case":"Get a Xero Coach. Get ahead.","ratio":"1:1","variants":3}'
curl -X POST localhost:8000/api/brands/xero/jobs/<job_id>/run   # execute the pipeline
curl localhost:8000/api/brands/xero/jobs/<job_id>               # poll status → done
curl localhost:8000/api/brands/xero/jobs/<job_id>/manifest   # layered manifest
curl -X POST localhost:8000/api/brands/xero/jobs/<job_id>/edits \
  -H 'content-type: application/json' \
  -d '{"parent":"generated","instruction":"change headline to '\''Books done. Life on.'\''"}'
```
