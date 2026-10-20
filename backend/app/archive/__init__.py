"""ARCHIVED — the old generate-then-strip path (kept for reference, not imported).

This was the pipeline where the image model painted EVERYTHING (text, logos,
background), then code reverse-engineered the result: detect windows → measure
ink → masked strip text/logo → paste live layers back at measured bboxes.

Replaced by the layout-first pipeline (app.layout + app.compose.fill): reasoner
places real pieces on a blank canvas (judged + perfected), the image model only
fills the blank space (colour-controlled), and the manifest is separation by
construction — nothing to strip, no text/logo divergence possible.

Modules: wireframe (labeled-box spec), composer (compose/fix/strip + composite
back), critic (bake judge + strip verify), layout_tune (vision placement tune),
textfit (measure + replace policy), match (NCC template match).
"""
