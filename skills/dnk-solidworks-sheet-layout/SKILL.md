---
name: dnk-solidworks-sheet-layout
description: Place SOLIDWORKS drawing views and reserve full-sheet keep-outs using measured outlines and annotation extents.
---

# Sheet layout

Use sheet coordinates in millimetres from the lower-left corner. Read the `dnk-solidworks-cad-house-standard` skill for the current review profile. Every inserted view must name its exact open model_reference and configuration.

## Measured layout

1. Call list_drawing_sheets and confirm paper size, scale, and units.
2. Call list_drawing_views; use measured outline_mm instead of screenshot guesses.
3. Build keep-outs from the measured frame insets, full title-block cluster, revision-table bounds, leaders, all annotation boxes, and a reserved dimension band around views. Keep the binding-side 20 mm filing margin for A-series sheets where the stock format uses it.
4. Place views with clear gaps, then call drawing_set_view and re-list outlines to confirm the measured result.
5. After the final annotation is added, run drawing_arrange_dimensions for affected views and re-run the full-sheet audit.
6. Run drawing_layout_audit, then inspect a raster rendering of the entire sheet. Its annotation boxes are estimates; leaders, border geometry, fonts, glyphs, line weights, and text overflow need visual review.

## Projection and source identity

For an orthographic set, insert one master with `drawing_insert_view`, then
create each companion with `drawing_insert_projected_view`, always passing the
same exact master name as `parent_view`. First-angle places top below the
master and right-side left; third-angle places top above and right-side right.
The projection tool's direction means sheet placement, not view orientation.
Prefer exact sheet coordinates after measuring outlines; verify projected
types, positions, and source identity. SW2026 may omit orientation read-back
for projected views, so confirm the convention from the sheet setting,
projection symbol and raster. Add all projections before creating another
sheet. Use `drawing_insert_standard_views` only for an explicitly requested
direct batch. Every model view must resolve to the requested open model and
configuration; live 34.0 reads configuration back, while another binding may
expose only that it was set.

## Dimension bands

Reserve a clear band on every side where dimensions or leaders will be placed. The feature coverage audit requires an explicit mapping from named design-critical features to stable IDs from list_drawing_dimensions. It detects missing assignments, stale IDs, and duplicate assignments; it does not infer intent from edge counts.
