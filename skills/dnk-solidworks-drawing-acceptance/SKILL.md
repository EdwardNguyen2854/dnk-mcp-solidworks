---
name: dnk-solidworks-drawing-acceptance
description: Ordered review and release gates for a SOLIDWORKS drawing, from source intake through verified native reopen and full-sheet raster review.
---

# Drawing acceptance

Use this gate before reporting a drawing complete. Separate review acceptance from manufacturing release.

## Gate

1. **Source identity and model health.** Record the exact model path and configuration, feature tree, rebuild state, mass properties, exact extrema, topology, and a source fingerprint. Stop on rebuild errors.
2. **Drawing profile.** For the agreed review profile use A3 landscape, first-angle projection, millimetres, and revision A. Unknown material, functional fits, datums, finish process, and approval fields remain unconfirmed.
3. **Explicit view references.** Create one master with `drawing_insert_view` and the exact `model_reference` and `configuration`; derive orthographic companions with `drawing_insert_projected_view`, passing the same master name each time. Verify every view's type, position, resolved model path and configuration with `list_drawing_views`; record any configuration read-back limit. SW2026 may omit projected orientation read-back, so confirm the convention from the sheet setting, projection symbol and raster. Use the direct standard-view batch only when explicitly requested.
4. **Sheet and keep-outs.** Verify the measured sheet and frame. Keep view outlines, dimensions, notes, leaders, title block, and revision table inside appropriate keep-outs. Use measured outlines and a full-sheet raster review.
5. **Dimension meaning and coverage.** Read dimensions from SOLIDWORKS annotation data. Add only dimensions supported by design intent and re-space after the final annotation. Use drawing_audit_feature_coverage with explicit feature refs and dimension IDs; investigate missing critical features, duplicate assignments, and stale IDs. Edge counts never define feature quantity.
6. **Tolerances and fits.** Apply only confirmed tolerances. ISO 2768-1:1989 remains current for general linear/angular tolerances where adopted; ISO 22081:2021 supersedes withdrawn ISO 2768-2 for general geometrical specifications. Do not use the obsolete combined ISO 2768-mK callout. H7 denotes a hole; shaft zones are lowercase. Show a mating fit only when both mating components and the fit are specified.
7. **Semantic annotations.** Verify datums and feature-control frames through annotation data. Use hole callouts only where SOLIDWORKS reports native hole-callout data. Current compound holes and cosmetic threads are geometry-only. Do not assign blanket finish; identify surfaces and process first.
8. **Title block and revisions.** Verify linked properties and their rendered/resolved values. Confirm latest revision row equals the revision property. Report stock-frame/static-field limitations.
9. **Layout checks.** Run drawing_layout_audit across the full sheet. Review estimated annotation collisions, off-frame content, revision-table bounds, duplicate notes, frame, title block, leaders, and overflow. API estimates are screening data; inspect the PDF/native raster directly.
10. **Glyph rendering.** Use SOLIDWORKS annotation data plus a rendered raster to verify diameter, degree, tolerance, and callout symbols. PDF text extraction alone is insufficient for glyph meaning.
11. **Export and reopen.** Export the review PDF, verify page and geometry structure, save/close/reopen the native drawing, and repeat manifest and validation. Confirm the source model remained unchanged.
12. **Release decision.** Keep the status at review while functional intent, material/process, datums, tolerances, required approvals, or human checks remain open. Only the design authority can close those items and authorize release.

## Report

State the observable checks and their evidence, the view references/configurations and readback limits, feature coverage results, any unconfirmed design inputs, raster/PDF checks, reopen result, and whether the result is review or released. Never promote a clean API validation into a release claim.
