# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases are tagged
`vMAJOR.MINOR.PATCH`.

## [Unreleased]

### Changed

- Renamed the distribution and product identity to **dnk-mcp-solidworks**
  (`dnk-mcp-solidworks` console script, `solidworks-mcp-core` and
  `solidworks-mcp` kept as aliases). The Python import package remains
  `solidworks_mcp`, so existing scripts and MCP client commands that use
  `python -m solidworks_mcp` keep working.
- Renamed the bundled workflow skills to the `dnk-solidworks-*` namespace
  (`dnk-solidworks-iso-engineering-drawing`,
  `dnk-solidworks-cad-house-standard`, `dnk-solidworks-drawing-acceptance`,
  `dnk-solidworks-sheet-layout`, `dnk-solidworks-cad-remodel`,
  `dnk-solidworks-image-assisted-modeling`). Reinstall the pack after upgrading;
  skill IDs changed, so agent-side references must be updated.
- Default write sandbox and log/checkpoint folders now use `dnk-mcp-solidworks`.
  Existing checkpoints stay in the old `%LOCALAPPDATA%\MCP-Solidworks` folder
  unless moved manually.

### Added

- Selection references for engineer-in-the-loop workflows: `get_selection`
  reads the engineer's current selection as bounded, labeled entity references;
  `resolve_entity_reference` revalidates them against the active document using
  SOLIDWORKS persist references with a geometric-fingerprint fallback and
  explicit failure codes (`REFERENCE_NOT_FOUND`, `REFERENCE_AMBIGUOUS`,
  `REFERENCE_DOCUMENT_MISMATCH`); `highlight_entities` transiently selects
  referenced entities as a view action. Live acceptance:
  `scripts/acceptance_selection.py` (11/11); identity measurement:
  `scripts/probe_persist_reference.py` (17/17).
- Geometry and model diagnostics: maximum-accuracy mass properties with status,
  exact body extrema, trimmed edge endpoints/closed state, tessellation-based
  model comparison with required caller tolerances, sketch constraint state and
  source-plane transforms, and probed extrude/cut depth readback.
- Explicit drawing references: view insertion now requires an open model
  reference and configuration, verifies the referenced model on the created
  view, and reports the configuration readback limit of typelib 34.0.
- Feature-aware dimension coverage: dimension state IDs and
  `drawing_audit_feature_coverage` detect missing critical coverage, stale IDs,
  and duplicate assignments using a caller-provided feature map.
- Typed batch annotation updates resolve stable IDs, rebuild once, verify
  readback, and roll back captured values on failure. Full-sheet layout audit
  now includes title-block/frame notes and exact revision-table bounds where
  the table API exposes them.
- A `dnk-solidworks-cad-remodel` skill and updated review-drawing skills define separate
  source preservation, geometry comparison, full-sheet raster checks, and
  review-versus-release gates.
- An `dnk-solidworks-image-assisted-modeling` skill guides image-referenced part creation with
  explicit known/estimated/unknown geometry, clarification gates, editable
  features, measured checks, and screenshot review. It does not claim automatic
  image-to-CAD conversion; image interpretation stays in the agent client.
- Native Hole Wizard creation remains guarded: the exploratory call crashed in
  `mfc140u.dll` on SW2026 SP0.0. Compound hole tools report geometry-only
  semantics and do not claim native hole-callout support.
- Wave-1 3D feature depth: reference extrude/cut end conditions (up-to-surface,
  offset-from-surface, up-to-body, up-to-vertex), `revolve_cut`, `thin_extrude`,
  face fillets, chamfer variants, `cosmetic_thread`, `counterbore_hole`,
  `countersink_hole`, `tapped_hole` and `dome`. Added the `select_bodies`
  helper. Live hand-calculation suite: `scripts/acceptance_modelling_depth.py`
  (26/26 passed); existing part acceptance remains 43/43.
- Wave-2 `combine_bodies` (add/subtract/common) is live-accepted through the
  registered MCP tool: `scripts/acceptance_combine_bodies.py` (26/26) checks
  measured volumes against hand calculations, one resulting body, one new
  Combine feature, clean rebuild, and pre-COM rejection of invalid indices.
  Evidence remains limited to the overlapping rectangular-prism fixture on
  SW2026 SP0.0; other geometry and versions are unverified.
- `capture_screenshot` accepts `view: "current"`, which captures the engineer's
  current camera without applying a standard view first. The existing default
  (`isometric`) is unchanged, so current callers behave exactly as before; an
  agent-facing integration can now look at the model without rotating the
  viewport.
- Hardened datum selection: reference candidates fail closed when their geometry
  cannot be read completely, highlight leases are owned and cleared by identity,
  planar-face references can be revalidated for offset-plane mutation, and edge
  fingerprints sample the trimmed span instead of the untrimmed support curve.
- Drawing annotation editing: `list_drawing_annotations` now reports a stable
  per-view `index`, the dimension `reading` (value with prefix/suffix) and a
  note's `resolved_text` for `$PRP` property links. New tools
  `drawing_move_annotation`, `drawing_delete_annotation`,
  `drawing_set_annotation_text` (note text and height; dimension
  prefix/suffix), `drawing_add_dimension` (dimensions picked view edges from
  `list_drawing_view_edges`) and `drawing_delete_view`.
- End-to-end ISO drawing demo: `scripts/iso_drawing_demo.py` builds a bracket
  and drives the whole standard workflow (views, designed dimensions with
  tolerances, datum/GD&T, finish, revision table, validation, PDF/PNG) with
  hand-calculated checks. It fills the stock frame's real title-block cells
  (part `Description`/`Material`/`Finish` via `$PRPSHEET`, drawing
  `DrawnBy`/`CheckedBy`/dates/`Revision` via `$PRP`, revision-free file name
  for DWG NO.), closes its own documents, and runs 69 checks.
- Flange housing demo: `scripts/iso_flange_demo.py` revolves a bearing flange
  housing (flange ring + hub ring, a 6X bolt circle, root fillet, chamfers)
  and drives the full ISO A3 workflow with 76 checks. Every feature is verified
  against a hand-calculated volume (Pappus rings for the fillet and chamfers)
  before the next one runs, the drawing is dimensioned from measured view
  edges (H7 bore fit, `6X Ø9 EQ SP` on a `78 B.C.`, position FCF on A|B) and
  the export is verified as PDF, DXF and PNG. Outputs land in
  `artifacts/flange-drawing-demo/`.
- `set_file_property`: set one text custom property on the active
  part/assembly/drawing with read-back verification; this is how model-side
  title-block links are filled.
- `list_drawing_annotations` resolves `$PRP`/`$PRPSHEET` note links to their
  displayed text (`resolved_text`), including referenced-model properties and
  `SW-File Name`.
- `drawing_layout_audit`: screens all returned sheet text, including title-
  block and frame notes, with estimated annotation boxes; it reports
  collisions, duplicate notes, off-frame items, and exact revision-table
  bounds where available. Raster inspection remains required for leaders,
  rendered glyphs, line weights, and actual text overflow.
- Drawing annotation depth: `list_drawing_view_edges` (index-addressed
  visible edges), `list_drawing_dimensions`, `drawing_set_dimension_tolerance`
  (symmetric, bilateral, limits, min/max, ISO fit), `drawing_insert_datum`,
  `drawing_insert_gtol`, `drawing_insert_surface_finish`,
  `drawing_insert_general_tolerance_table`, `drawing_insert_revision_table`,
  `drawing_add_revision`, `drawing_insert_hole_callout`.
- Drawing release review: `drawing_manifest` (sheets, views, annotations,
  properties, rebuild state), `drawing_preflight` (frame/projection/view
  checks) and `validate_iso_drawing` (release contract with
  `readable_dimensions` and title-block link checks).
- Bundled workflow skills: `skills/dnk-solidworks-iso-engineering-drawing/SKILL.md`,
  `skills/dnk-solidworks-cad-house-standard/SKILL.md`,
  `skills/dnk-solidworks-drawing-acceptance/SKILL.md`, `skills/dnk-solidworks-sheet-layout/SKILL.md` and
  `skills/dnk-solidworks-cad-remodel/SKILL.md`,
  plus `python -m solidworks_mcp --install-skill <dir>` to copy them into an
  agent's skills directory.
- Optional HTTP transport alongside stdio.

### Changed

- Tool surface: 134 -> 138 tools (42 core / 96 extended); README, AGENTS.md
  and the skill pack are in sync with the catalog.
- Unit suite includes checkpoint path/type, PDF page-count, geometry comparison,
  feature coverage, and image-content regressions.
- Live suites: 43 part-geometry, 68 assembly/drawing, 50 ISO-annotation and
  28 drawing-edit checks (`scripts/acceptance_drawing_edit.py`).

### Fixed

- Section and detail views were created from sheet coordinates while a drawing
  view sketch's origin is the view's centre, so the boundary geometry missed
  the model: `drawing_insert_section_view` returned a view SOLIDWORKS labels
  `section` that was never cut (no cut contour, no bolt-hole voids, no
  hatching), and a detail circle enclosed the wrong region. Both tools now
  convert sheet millimetres into the view's sketch space, and
  `drawing_insert_section_view` verifies the cut by read-back - a section that
  exposes no cut edges raises instead of passing silently. Verified at 1:1 and
  2:1 against the DXF export (`scripts/iso_flange_demo.py`).
- `drawing_add_note` with `height_mm` silently never applied the height:
  `IAnnotation.GetTextFormat()` without an argument raises "Type mismatch" on
  SW2026 SP0.0. The height now goes through `INote.GetTextFormat()` and is
  verified by read-back, as does `drawing_set_annotation_text`.
- Dimension tolerances were set and read in **metres** while the tool surface
  is millimetres: `value_mm=0.2` rendered as `±200.00`. `SetValues` now
  converts mm to metres and `GetMinValue`/`GetMaxValue` convert back.
- Surface finish roughness went to the `MachAllowance` parameter, which is
  not drawn; the value now goes to `MaxRoughness` and the annotation listing
  reads all seven `ISFSymbol` text slots. Measured on SW2026 SP0.0 the symbol
  still renders the value at zero height (the placeholder line), so the demo
  adds a visible `Ra x.x` companion note; see `docs/COM-QUIRKS.md`.
- ISO fits can now be hole-only (`shaft_fit` optional), so a hole callout
  reads `2X Ø10 H7` instead of a full hole/shaft pair.
- `list_drawing_view_edges` measured line edges in the 2D projection, so an
  edge along the view's depth axis (the side-view thickness edge) reported
  zero length; the report now carries the true 3D length, out-of-plane
  `depth_mm`, and `start3_mm`/`end3_mm`.
- The revision table was anchored with its bottom-left corner at the frame's
  top-right corner, so it grew up and right across the border.
  `drawing_insert_revision_table` now unanchors it and places it 2 mm inside
  the frame (`inside_frame` in the result).
- `create_checkpoint` on an unsaved document resolved `Path("")` to `.` and
  failed with "Permission denied: '.'". Unsaved documents now take the
  save-a-copy branch, with an extension matching the document type.
- `rollback_to_checkpoint` reopened the copy with `OpenDoc6` auto type, which
  fails on SW2026 SP0.0 (`error_code 1024`); the open type now follows the
  checkpoint's file suffix, as `open_document` already did.
- `verify_export` read an outline `/Count` as the PDF page count (a one-page
  PDF reported as five pages). Page objects are now authoritative, the
  declared count is kept for diagnostics, and a mismatch sets
  `page_count_consistent` to false.

## [0.4.0] - 2026-09-26

### Added

- Drawing sheets: `list_drawing_sheets` (paper size, scale, size in mm),
  `drawing_add_sheet`, `drawing_activate_sheet`.
- Drawing views: `drawing_activate_view`, `drawing_set_view` (position, scale,
  display mode, tangent edges), `drawing_insert_projected_view`,
  `drawing_insert_section_view` (cutting line drawn in the parent),
  `drawing_insert_detail_view` (detail circle drawn in the parent),
  `drawing_create_sketch`, `drawing_insert_center_marks`,
  `drawing_insert_centerlines`; `list_drawing_views` now reports each view's
  type, position, scale and referenced model.
- `set_appearance`: model-level or per-face colour with 8-bit read-back
  verification.
- `list_faces` gained surface-type, minimum-area and normal filters;
  `list_edges` gained curve-type and minimum-length filters. Filtered results
  keep the global indices the feature tools accept.
- Sketch tools now work inside a drawing view sketch (`drawing_create_sketch`).

### Changed

- Tool surface: 88 -> 100 tools (39 core / 61 extended).
- Standard drawing view names resolve through the model's own
  `GetModelViewNames`, so they survive localized SOLIDWORKS installs.
- Live suites grew to 43 part-geometry and 56 assembly/drawing checks;
  `scripts/acceptance_asm_drw.py` accepts test names to run a subset.

### Fixed

- `exit_sketch` accepts a drawing and reports the measured inability to close
  a drawing view sketch (`view_sketch: true`) instead of failing with a wrong
  document type.

### Known gaps

- `rib` is withheld: `InsertRib` builds nothing on SW2026 SP0.0 (see
  `docs/COM-QUIRKS.md`).
- Projected views: one per drawing, and `CreateUnfoldedViewAt3` returns
  nothing once a second sheet exists (measured; see COM-QUIRKS).

## [0.3.0] - 2026-09-26

### Added

- Sketching depth: `sketch_arc`, `sketch_arc_3point`, `sketch_ellipse`,
  `sketch_slot`, `sketch_point`, `sketch_trim`, `sketch_mirror`,
  `sketch_fillet`, `sketch_chamfer`, `sketch_construction`, `list_sketches`,
  `edit_sketch`, `list_dimensions`, `set_dimension`.
- Features: `simple_hole` (located from the face selection's `ISelectData`
  X/Y/Z), `draft`, `sweep`, `loft`, `set_feature_suppression`.
- Reference geometry and inspection: `create_axis`, `list_reference_planes`,
  `list_vertices`, `measure` (faces, edges, vertices).
- Assemblies: `list_mates` (mates read back through `IMate2`),
  `set_component_fixed`.

### Changed

- Tool surface: 63 -> 88 tools (39 core / 49 extended).
- Live suites grew to 43 part-geometry and 33 assembly/drawing hand-calc
  checks; 34 unit tests.
- Component selection in `set_component_fixed`/`insert_component` now uses
  `GetSelectByIDString` + `SelectByID2`; `Select2` alone fails on mated
  components.

### Fixed

- `SketchTrim` returns False on success; the sketch fingerprint (segment
  count + total length) is the judge. Sketch fillet/chamfer use
  `SketchFillet2`/`SketchChamfer`, which need a two-segment selection.

### Known gaps

- `rib` is withheld: `InsertRib` builds nothing on SW2026 SP0.0 under every
  documented combination (see `docs/COM-QUIRKS.md`); re-probe on a later
  build.

## [0.2.0] - 2026-09-25

### Added

- Modeling: `create_reference_plane` (offset, midplane, angle),
  `linear_pattern`, `circular_pattern`, `mirror_feature`.
- Drawings: `drawing_insert_model_dimensions`, `drawing_auto_dimension`,
  `drawing_add_note`, `list_drawing_annotations`; `list_drawing_views` now
  reports per-view dimension counts and flags the sheet entry.
- Export: `verify_export` reports structural facts (PDF pages, DXF entities and
  extents, STL triangles and bounding box, STEP/IGES sections); every
  `export_document` result carries a format signature check.
- Docs: `docs/PRIOR-ART.md` reference ledger, this changelog.

### Fixed

- Single-ended `FeatureCut4` cuts built nothing because the `Dir` flag was
  never set. Cuts now try the requested direction and retry the other way,
  reporting `reversed_automatically`; `cut_extrude` gained `flip_side`.
- `InsertRefPlane` returns a dispatch that does not QueryInterface to
  `IFeature`; reference planes are now found and named through a feature-tree
  diff.

### Changed

- `docs/COM-QUIRKS.md` grew the patterns/mirror, single-ended cut and drawing
  annotation sections; `AGENTS.md` and the README are in sync with the new
  surface and test counts (63 tools).
- Test suites: 30 unit tests, 20 part-geometry acceptance checks, 29
  assembly/drawing acceptance checks.

## [0.1.0] - 2026-09-25

Initial private release: MCP stdio server over a single STA COM worker, early
binding with interface wrapping, tiered typed tools, the sketched part loop,
assemblies, drawings, checkpoints and rollback, export and screenshot evidence,
and sandboxed writes.
