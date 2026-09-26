---
name: drawing-acceptance
description: Ordered release gate for a SOLIDWORKS drawing, from part intake to verified PDF export.
---

# Drawing acceptance

Run this gate before calling any drawing done. Each step names the tools that
produce the evidence; a step that cannot be satisfied is a stop condition, not
a footnote.

## Gate

1. **Model intake.** `rebuild_document` and stop on `What's Wrong` entries
   (`check_errors`). Record `get_mass_properties`, `get_bounding_box` and the
   feature list (`list_features`) so view selection and dimensions have a
   source of truth.
2. **Frame and units.** `list_drawing_sheets` must report the ISO paper size
   (A4-A0), the intended scale, and millimetres. Run `drawing_preflight`;
   `view_bounds` and `view_overlap` must be clean.
3. **Views.** `list_drawing_views` gives names, types, positions and outlines.
   Fix placement and scale with `drawing_set_view`; correct view deletion is
   `drawing_delete_view`. Only add sections/details when the primary views
   cannot describe the part.
4. **Dimensions.** `list_drawing_dimensions` (value, position, tolerance,
   hole-callout state) proves what is on the sheet. Add missing intent with
   `drawing_add_dimension` on edges from `list_drawing_view_edges`; space them
   with `drawing_arrange_dimensions`; set required tolerances with
   `drawing_set_dimension_tolerance`. Every position-toleranced feature is
   located by **basic (boxed)** dimensions from the datum edges — never by
   plain ± dimensions at the same time. Confirm every location a machinist
   needs is present (for a hole: X, Y and diameter; for a slot: width, length
   and X/Y of its centre). Add the ISO 2768-mK note via `drawing_add_note`
   (height is verified by the tool); it applies only to dimensions without an
   individual tolerance.
5. **Annotations.** `list_drawing_annotations` returns per-view indexes, a
   dimension `reading` and a note `resolved_text`. Clean up with
   `drawing_move_annotation`, `drawing_delete_annotation` and
   `drawing_set_annotation_text`. Center marks for circular features via
   `drawing_insert_center_marks`. No annotation may overlap another or leave
   the frame; positions come from the listing, never from a screenshot guess.
   Read the hole callout as a machinist would: `2X Ø10 H7` is unambiguous,
   `Ø10 H7/h6` (a hole/shaft pair) or an unlabelled fit is not.
6. **Semantic symbols.** Datums (`drawing_insert_datum`), geometric tolerances
   (`drawing_insert_gtol`) and surface finish (`drawing_insert_surface_finish`)
   attach to edges from `list_drawing_view_edges` and verify their own
   read-back. Every datum referenced in a feature-control frame must have a
   visible datum feature symbol on the drawing. The surface finish symbol
   stores its value (`GetText(5)`) but renders it at zero height on this
   build, so add a companion `Ra x.x` note and say so in the report. A hole
   callout is only valid for holes with callout data
   (`drawing_insert_hole_callout`); otherwise report, do not fake a note.
7. **Title block and revision.** `drawing_set_property` writes and reads back
   the fields; `drawing_insert_revision_table` + `drawing_add_revision` keep
   the table's current revision equal to the `Revision` property. The stock
   ISO frame's cells are static on this build, so when no company template
   links them, repeat the fields (part name, drawing number, material,
   revision, scale, units, drawn/checked/date) in a `drawing_add_note` data
   block next to the title block, and say in the report that the frame is
   not property-linked. Check the revision table sits inside the frame
   (`drawing_insert_revision_table` reports `inside_frame`).
8. **Validate.** `drawing_manifest` for the full inventory, then
   `validate_iso_drawing` with the required views and title-block fields.
   Correct every error.
9. **Audit the layout, then export.** Run `drawing_layout_audit` and require
   zero collisions and zero off-frame items; it estimates boxes from measured
   positions and skips the sheet-format border band and title block, so treat
   a finding as a real overlap until proven otherwise (move annotations with
   `drawing_move_annotation` and re-run). Then `export_document` to PDF (and
   DXF when the shop wants it) and `verify_export`: the PDF must report
   `page_count` and `page_count_consistent=true`; DXF entity counts and
   extents must match the sheet. Text-level PDF read-back (for example with
   PyMuPDF) is an external check, not a server tool — use it when available to
   confirm dimension text rendered, and say so in the report.
10. **Reopen check.** Save the drawing, close it, reopen it, and re-run
    `drawing_manifest` + `validate_iso_drawing`. A file that only validates in
    the live session is not released.

## Report format

State separately:

- `validated observable state` — every check above with its measured values;
- `open items` — missing GD&T, title-block artwork, tolerance policy, visual
  checks (line weights, fonts) that require human review;
- `deviations from the house standard`, naming each overriding value.
