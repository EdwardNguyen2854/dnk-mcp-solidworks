---
name: dnk-solidworks-iso-engineering-drawing
description: Create and review an ISO metric part drawing in SOLIDWORKS with explicit model references, feature coverage, full-sheet checks, and release gates.
---

# ISO Engineering Drawing

Use this workflow for an ISO metric drawing. It coordinates the typed SOLIDWORKS MCP tools and preserves the distinction between a review drawing and a released drawing.

## Intake

Record the exact source model path, document type, configuration, drawing number, title, requested revision, and output paths. Treat unknown material, functional fits, datum scheme, process/finish requirements, checker, and approver as unconfirmed. Read the `dnk-solidworks-cad-house-standard` skill for the agreed profile.

## Workflow

1. Call get_capabilities; confirm the running SOLIDWORKS revision, template, and guarded capabilities.
2. Record the source model path/configuration and feature tree. Rebuild and stop on What's Wrong. Capture mass properties, exact extrema, topology, and a source screenshot when geometry changes are in scope.
3. Create or prepare the A3 landscape drawing in millimetres, first-angle projection, revision A review profile. Never describe the stock ISO frame as a company title block.
4. Create one master view with `drawing_insert_view`, using the exact open
   `model_reference` and `configuration`; use front unless the drawing intent
   calls for another master. Save its returned view name. Create each
   orthographic companion with `drawing_insert_projected_view`, always passing
   that same name as `parent_view`. For first-angle, place top below the master
   and right-side left; for third-angle, place top above and right-side right.
   `direction` describes sheet placement, not orientation. Add projections
   before any second sheet exists.
5. Call `list_drawing_views` and verify master/companion types, measured
   positions and outlines, and each view's resolved model reference and
   configuration. Live 34.0 acceptance reads configuration back; record it as
   unavailable if another binding's getter fails. SW2026 may omit projected
   orientation read-back, so confirm the convention from the sheet setting,
   projection symbol and raster. Use
   `drawing_insert_standard_views` only when direct batch insertion is
   explicitly requested. Reserve keep-outs for the sheet frame, title-block
   cluster, revision table, leaders, existing annotations and dimension bands.
   Use the lower-left sheet origin in millimetres; re-list outlines after edits.
6. Set title-block-linked properties individually. Compare the API property values with each linked note's rendered/resolved value. Keep missing material, checked-by, and approved-by fields explicitly unconfirmed.
7. Add centre marks, section/detail views, datums, GD&T, and surface-finish symbols only where design intent supports them. Attach symbols to their intended feature. A surface-finish value can read back yet render incorrectly on this build; pair with a clear note only when the specified process supports it and verify the rendered result.
8. Import model dimensions and compare annotation inventories before and after. If none import, use auto-dimension only as a review aid. Arrange dimensions after the final annotation is added.
9. Build an explicit feature-to-dimension coverage map using model feature names and IDs from list_drawing_dimensions; call drawing_audit_feature_coverage. Investigate every missing critical feature, stale dimension ID, or duplicate assignment. The map is caller-declared and cannot prove functional intent by itself. Never infer hole quantity from edge count.
10. Apply only confirmed tolerances. ISO 2768-1:1989 remains current for general linear/angular tolerances where adopted. ISO 22081:2021 supersedes withdrawn ISO 2768-2 for general geometrical specifications. Avoid a combined ISO 2768-mK note. H7 is a hole designation; shaft designations use lowercase. Do not assign a blanket surface finish.
11. Add the revision table and verify its latest row matches the Revision property. Run drawing_layout_audit over the full sheet; inspect text estimate collisions, off-frame notes, exact revision-table bounds, and known blind spots.
12. Run drawing_manifest, validate_iso_drawing, and a full-sheet raster review. Read symbols and dimension meaning through SOLIDWORKS annotation data and the raster. Do not treat PDF text extraction as authoritative for diameter or degree glyphs.
13. Export the review PDF. Reopen the native drawing and rerun the manifest and validation. Confirm the source model remains open/unchanged when the workflow started from it.

## Hole semantics

Use drawing_insert_hole_callout only when SOLIDWORKS reports native callout data. The current target's HoleWizard5 probe crashed in mfc140u.dll, so native Hole Wizard creation remains withheld pending a safe live acceptance path. Current simple/counterbore/countersink/tapped-hole operations report geometry-only semantics; do not represent them as native callouts.

## Release gate

A clean tool validation is only observable-state evidence. A drawing stays a review drawing while any functional requirements, material/process, datum scheme, tolerance policy, title-block approvals, or required human raster review remain unresolved. Report each open item and do not claim manufacturing release.
