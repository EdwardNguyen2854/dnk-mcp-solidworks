---
name: iso-engineering-drawing
description: Create and release-review an ISO metric part drawing through the SOLIDWORKS MCP tools.
---

# ISO Engineering Drawing

Use this skill for an ISO metric part drawing. The skill coordinates the MCP
tools; it does not bypass them or claim that a plain note is a semantic
dimension, tolerance, datum, or symbol.

## Contract

Required inputs:

- model path or an active part
- drawing number
- title
- revision
- material when known
- output path for the source drawing and PDF

Defaults:

- ISO metric profile
- A3 landscape stock frame
- first-angle projection
- front, top, and right model views
- model dimensions first; DimXpert auto-dimension only as a fallback

The stock ISO frame is not a company-specific title block. Do not describe the
result as manufacturing-release compliant unless the human/company review has
approved the frame, drafting standard, tolerances, and annotations.

## Workflow

1. Call `get_capabilities` and confirm the active SOLIDWORKS revision and
   drawing template.
2. Confirm the source model is a part, rebuild it with `rebuild_document`, and
   stop on any `What's Wrong` entries.
3. Call `new_drawing` with `paper_size="A3"`, `scale=1.0`, and
   `first_angle=true`.
4. If working in an existing drawing instead, call `drawing_set_iso_units` and
   stop if millimetre read-back fails.
5. Call `drawing_insert_standard_views` for front, top, and right views.
6. Call `list_drawing_views`, then use `drawing_set_view` to correct positions,
   scale, hidden-line mode, and tangent-edge display. Keep every model view
   inside the usable sheet area and do not add a second sheet before any
   required projected-view operation.
7. Set title-block-linked properties individually with `drawing_set_property`:
   `DrawingNumber`, `Title`, `Revision`, and known fields such as `Material`,
   `Scale`, `Projection`, `DrawnBy`, `CheckedBy`, and `ApprovedBy`.
8. Add center marks and centerlines for circular features. Add sections or
   details when they make the model easier to manufacture from: the cutting
   line and detail circle take sheet millimetres and are converted into the
   parent view's sketch space, and a section whose cut cannot be verified is
   reported as an error — fix the parent/line coordinates instead of shipping
   it. The circular view yields a single centre mark on this build.
9. Try `drawing_insert_model_dimensions` when the model has intentional
   dimensions marked for drawing. If it adds nothing on SW2026 SP0.0, use
   `drawing_auto_dimension` and then `drawing_arrange_dimensions`. Treat those
   dimensions as requiring design-intent review, not as automatic compliance.
   For every position-toleranced feature, locate it with **basic (boxed)**
   dimensions from the datum edges: `drawing_set_dimension_tolerance(
   tolerance="basic")`. A linear dimension from a line to a circle measures to
   the circle centre, so datum-referenced locating dimensions need no
   construction geometry.
10. Set tolerances where the design requires them: `list_drawing_dimensions`
    gives indices, `drawing_set_dimension_tolerance` sets symmetric, bilateral,
    limits, min/max, or ISO fit values (`shaft_fit` optional for hole-only
    callouts such as `2X Ø10 H7`), and each call verifies the measured
    read-back. Values are millimetres on the tool surface.
11. Add the general tolerance default with `drawing_add_note`:
    `UNLESS OTHERWISE SPECIFIED: GENERAL TOLERANCES ISO 2768-mK`. On parts and
    assemblies `drawing_insert_general_tolerance_table` inserts the DimXpert
    table instead; on drawings the note is the measured path.
12. Attach semantic annotations to features that need them:
    `list_drawing_view_edges` addresses the edges, then `drawing_insert_datum`
    (for example A), `drawing_insert_gtol` (characteristic, tolerance,
    diameter flag, datum references) and `drawing_insert_surface_finish`
    (roughness value). Define a datum scheme first (primary face, long edge,
    short edge) and make **every referenced datum has a visible datum feature
    symbol**; a position frame that references A|B|C must have A, B and C on
    the sheet. Each tool verifies its own read-back; do not fake any of these
    with plain notes.
13. Add the revision table with `drawing_insert_revision_table`, then
    `drawing_add_revision` for each revision row; the latest revision must
    match the `Revision` property.
14. Add concise manufacturing notes with `drawing_add_note`. Do not encode
    GD&T, surface finish, hole callouts, or other semantic symbols as notes.
15. Call `drawing_manifest` and inspect sheets, view outlines, annotations,
    properties, and rebuild state.
16. Call `validate_iso_drawing` with at least three model views and the
    required title-block properties. Correct every error before exporting.
17. Call `export_document` for PDF and then `verify_export`. Save the source
    drawing, close it, reopen it, and run `drawing_manifest` and
    `validate_iso_drawing` again before reporting success.

## Assembly drawings

For an assembly drawing, in addition to the part workflow:

1. `drawing_insert_bom_table` inserts the parts list. The view's referenced
   configuration is resolved automatically; a header-only table is reported
   as an error, so pass `configuration` explicitly if the view does not
   reference the expected one.
2. `drawing_insert_balloons` auto-balloons the components; verify the balloon
   texts carry item numbers (the BOM table must exist first).
3. `drawing_insert_hole_callout` works only for holes that carry callout data
   (Hole Wizard holes). If the model uses simple cut holes, stop and report
   instead of faking a note.

## Stop Conditions

Stop and report a blocking limitation when:

- the sheet is not an ISO A4-A0 size or has no frame;
- the projection, scale, or view layout is wrong;
- the drawing rebuild has errors;
- required title-block properties cannot be read back;
- the required title-block links cannot be read back when strict display
  validation is enabled;
- dimensions are missing or their design intent is unknown;
- a required semantic annotation is unavailable through the verified tool
  surface;
- a hole callout is required but the hole has no callout data (not created
  with the Hole Wizard); do not replace the callout with a plain note;
- PDF export or source-document reopen verification fails.

The final report must distinguish `validated observable ISO state` from
`human/company-standard review still required`.
