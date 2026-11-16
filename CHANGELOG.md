# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases are tagged
`vMAJOR.MINOR.PATCH`.

## [0.1.0] - 2026-11-16

First public release. The repository history was restarted for publication, so
this entry describes the complete shipped state rather than a delta from a
private version.

### Added

- MCP server over stdio (default) and an opt-in loopback Streamable HTTP
  adapter, with one dedicated STA COM worker thread and a per-call timeout.
- Early-bound COM access with interface wrapping (QueryInterface + DISPID),
  typed double-array marshalling, and centralised millimetre/degree conversion.
- Typed tool registry with `core`, `extended`, `advanced`, and `debug` tiers and
  a `search_tools` meta-tool. Default profile: 143 tools (46 `core`,
  97 `extended`).
- Part modelling: sketches, relations, driving dimensions, trim/fillet/chamfer/
  mirror/offset/convert, boss and cut extrudes, revolve and revolve-cut, thin
  extrudes, fillets, chamfers, shell, holes, cosmetic threads, dome, draft,
  sweep, loft, suppression, materials, reference geometry, patterns, mirror, and
  `combine_bodies`.
- Closed-loop verification: mass properties, exact bounding box, What's Wrong,
  feature/face/edge/body/vertex listings, measurement, tessellation-based model
  comparison with caller tolerances, and screenshots as MCP image content.
- Selection references: `get_selection`, `resolve_entity_reference`, and
  `highlight_entities`, using SOLIDWORKS persist references with a geometric
  fingerprint fallback and explicit failure codes.
- Assemblies: deterministic component insertion, transforms with read-back,
  planar mates, mate listing, fix/float, and interference detection.
- Drawings: sheets, standard/projected/section/detail views, center marks and
  centerlines, model dimensions, DimXpert, notes, tolerances (including ISO
  fits), datums, GD&T, surface finish, revision and BOM tables, balloons, hole
  callouts, title-block properties, layout audit, ISO preflight, manifest, and
  PDF/DXF export.
- Transactions: debounced file checkpoints, listing, and rollback.
- Export: STEP, IGES, STL, 3MF, Parasolid, PDF, DXF, DWG, and images, with
  structural verification of the written artifact.
- Workflow skills: `dnk-solidworks-iso-engineering-drawing`,
  `dnk-solidworks-cad-house-standard`, `dnk-solidworks-drawing-acceptance`,
  `dnk-solidworks-sheet-layout`, `dnk-solidworks-cad-remodel`, and
  `dnk-solidworks-image-assisted-modeling`, installable with
  `python -m solidworks_mcp --install-skill <dir>`.
- Unit suite (no SOLIDWORKS required) plus live acceptance suites and demos that
  compare measured geometry against hand calculations, documented in
  `scripts/README.md`.
- Public project files: Apache-2.0 `LICENSE`, `NOTICE`, `CITATION.cff`,
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and PR
  templates, Dependabot, and Windows CI.

### Known gaps

- Validated against SOLIDWORKS 2026 SP0.0 (typelib 34.0) only. Other releases
  may differ; risky behavior is capability-guarded.
- Native Hole Wizard creation is withheld: `HoleWizard5` created no feature
  under the tested parameters and crashed during probing. Compound holes are
  geometry-only.
- `rib` is withheld: `InsertRib` built nothing on the tested build.
- Projected views: create projections before adding a second sheet, and one
  projection per drawing on the tested build.
- Equations, configurations, and batch plan execution are not implemented.
