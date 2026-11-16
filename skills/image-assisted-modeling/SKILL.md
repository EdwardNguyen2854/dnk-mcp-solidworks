---
name: image-assisted-modeling
description: Use when a user provides image(s) or a drawing of a mechanical object and wants an editable SOLIDWORKS part. If an existing CAD model is the source, use cad-remodel.
---

# Image-assisted modeling

Use drawing images as evidence for a native, editable SOLIDWORKS part. This is an agent-guided reconstruction workflow, not automatic image-to-CAD conversion.

## Workflow

1. **Set the target.** Confirm whether the user wants a concept, a dimensionally constrained review model, or another accuracy level. If an existing CAD model is the source, use `cad-remodel` and preserve it. Ask before creating a drawing; use `iso-engineering-drawing` when requested.
2. **Make the image visible.** Use an attached image when available. For a local path, call `view_reference_image`; it returns a PNG/JPEG as MCP image content with pixel metadata. If neither path works, ask for an attachment or an accessible reference. The tool does not OCR, trace geometry, infer physical scale, or reconstruct a model.
3. **Read the drawing before modeling.** Identify each front/top/side, isometric, section, and detail view. Use the marked projection convention where present; don't infer first- versus third-angle projection from layout alone. Record units, scale notes, section cuts, hidden geometry, centerlines, and explicit dimensions. Prefer orthographic and section views for size and location; use isometric views for shape context. Printed dimensions outrank pixel proportions.
4. **Create a dimension/evidence ledger before choosing geometry.** For each consequential requirement, record its value and unit, source view/callout, evidence class, planned feature or model dimension, and verification method. Use these evidence classes:
   - `user-supplied` — an explicit requirement or legible dimension in the provided drawing; transcribe the callout and source view.
   - `observed` — a visible shape or relationship, without assuming exact scale.
   - `estimated` — an approximation the user has approved.
   - `unknown` — hidden, illegible, conflicting, or unspecified information.

   Track the envelope, thickness/depth, major profiles, hole/interface sizes and positions, symmetry, and functional dimensions. Treat unreadable callouts as unknown, not as OCR results or guesses.
5. **Resolve consequential unknowns.** Ask for a higher-resolution image or dimension transcription when a callout is ambiguous. If scale is absent, ask for a known reference dimension or permission to make a labeled visual estimate. Ask about hidden geometry, thickness, interfaces, and accuracy where they change the model. Do not invent fits, material, process, or safety-critical requirements.
6. **Plan an editable feature tree.** State the coordinate orientation/origin, feature order, assumptions, and any uncovered ledger items. Map each design-critical dimension to a driving sketch/feature dimension where supported; report it as uncovered otherwise. Prefer a primary profile/base feature, then major bosses/cuts, repeated holes/patterns, and edge treatments. Check the live catalog/build before promising native semantics: some hole tools create geometry without native Hole Wizard callout data. Use registered typed tools and never silently substitute an unsupported feature.
7. **Build and verify in increments.** Check `get_status` and `get_capabilities`; the server attaches only to an already-running SOLIDWORKS session. Preserve unrelated documents and unsaved work; make a separate part with `new_document`. Build one logical sketch/feature at a time using millimetres/degrees. After major features, inspect rebuild/errors, `list_features`, dimensions, bodies, exact bounds, and mass properties as appropriate. Judge success by measured geometry, not a feature return value. Stop on unexplained failures or mismatches.
8. **Review against the evidence.** Use `set_view` and `capture_screenshot` for orthographic and isometric review. Compare measured dimensions and bounds with the ledger and hand calculations using explicit tolerances. Reconcile every critical ledger item as verified, uncovered, or unresolved. Visual comparison is manual: the server does not register or score the source drawing against projected model silhouettes, and screenshots cannot prove hidden geometry or engineering correctness.
9. **Save and hand off.** Confirm the destination when unspecified; save the new model separately with `save_document`. Report the path, feature-tree summary, ledger coverage, measured checks, estimates, and unresolved items. Label the result as concept/review or ready for further engineering review; never claim design approval or fitness for manufacture.

## Stop conditions

- The image cannot be made visible and the user has not supplied enough geometry.
- A critical scale, dimension, or hidden feature remains unknown for the requested accuracy.
- A critical drawing callout cannot be read or reconciled across views.
- The required feature or verification is unavailable in the live tool catalog/build.
- Rebuild errors or measured geometry disagree with explicit requirements and the cause is unresolved.

When stopping, name the missing evidence and ask for the smallest useful clarification. The MCP image tool only presents local PNG/JPEG evidence to the agent; it does not perform OCR, vectorization, automatic feature recognition, or network access.
