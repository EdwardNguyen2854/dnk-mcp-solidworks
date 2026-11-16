# Prior art: the public SOLIDWORKS MCP servers

This project is an open-source MCP server for SOLIDWORKS. It is a clean-room
implementation: we study the public servers, take the best idea from each, and
verify everything against the installed typelib before relying on it.
Checking this file before designing a feature is part of the workflow — one of
these projects has usually hit the same quirk already.

Licences and attribution live in `THIRD_PARTY_NOTICES.md`.

## The reference table

| Project | Main strength | Architecture | Notable capability |
|---|---|---|---|
| [czuryk/SolidworksMCP](https://github.com/czuryk/SolidworksMCP) | Production/agentic workflows | Python → COM | Transactions, rollback, verification, parametric modeling |
| [Slacker-LLC/solidworks-mcp](https://github.com/Slacker-LLC/solidworks-mcp) | Broad CAD manipulation | Python → COM | **92 tools**, assemblies, mates, screenshots |
| [hjbaard/SolidWorks-MCP](https://github.com/hjbaard/SolidWorks-MCP) | Closed-loop CAD agent | Python/pywin32 → COM | Build → measure → verify → correct |
| [just1step/solidworks-mcp](https://github.com/just1step/solidworks-mcp) | Easy deployment / architecture | .NET hub → COM | Single EXE, shared COM/STA session |
| [jaylamping/solidworks-mcp](https://github.com/jaylamping/solidworks-mcp) | Engineering-oriented architecture | TypeScript → .NET → COM | Checkpoints, tool tiers, persistent worker |
| [alisamsam/Solidworks-MCP](https://github.com/alisamsam/Solidworks-MCP) | Simple starting point | Python → COM | 22 straightforward modeling tools |

## Adopted / unmined, per project

| Project | Adopted here | Still unmined (candidate for a later release) |
|---|---|---|
| czuryk | Checkpoints + rollback (`tx/checkpoint.py`), capability discovery (`get_capabilities`), version guards, fail-loud envelope | Invariants, idempotency accounting, operation budgets → pairs with a batch/plan-execution milestone |
| Slacker-LLC | Declarative selection, explicit `_mm`/`_deg` units, screenshots as image content, the COM quirk playbook, mark assignments for patterns/mirror/ref-planes, sketch editing depth (arcs, 3-point arcs, ellipses, slots, trim, sketch fillet/chamfer, construction toggle, dimension read-back), `simple_hole`, `draft`, `sweep`, `loft`, `set_feature_suppression`, `create_axis`, `list_vertices`, `measure`, `list_mates`, `set_component_fixed` | Drawing breadth (sheets, projected/section/detail views, center marks), `set_appearance`, filtered selection listings, point/`face_edges` selection specs; `rib` is implemented here but withheld: `InsertRib` builds nothing on this SW2026 SP0.0 build (see COM-QUIRKS) |
| hjbaard | Evidence on every mutation, early binding with interface wrapping, dedicated STA worker, fail-loud errors | Fully mined — the architecture is the source of the binding strategy (ADR 0001) |
| just1step | One process owns the COM/STA session; a separate client proxy never touches COM | Single-EXE packaging, published support-matrix per SOLIDWORKS release |
| jaylamping | Tool tiers, debounced auto-checkpoints, allowed-roots sandboxing, version-guarded generated catalogs | Confirmation gates (deliberately not adopted: this server is agent-autonomous); generated catalog artifacts for docs |
| alisamsam | Minimal registry baseline, template discovery, version-aware fallbacks | An explicit "supported SOLIDWORKS versions" policy table |

## How to use the reference implementations

The Slacker-LLC server is the closest sibling (same language, same session
model, 92 tools) and its source is the best place to start when adding a tool
whose COM call is not obvious. Two habits that pay off:

- Its `solidworks_mcp/sw_feature.py`, `sw_refgeom.py` and `sw_drawing.py` show
  working selection marks for features it has shipped (patterns, mirror,
  `InsertRefPlane`, `InsertModelAnnotations3`). Marks are the part the
  published docs get wrong most often.
- Its README's "Notes from the implementation" and "Known limitations"
  sections list failure modes worth reproducing in our own probes (silent null
  returns, modal dialogs, localized view names, `circular_pattern` refusing
  body-separate features).

Never copy code: the codebase uses its own binding layer, envelope, error
taxonomy and testing standard. Copy the *knowledge*, then verify it on this
machine with `scripts/probe_api.py` and the live acceptance suites.

## Tool-surface diff (Slacker-LLC 92 tools vs this server)

Checked against the Slacker-LLC README and source on 2026-09-26. We
deliberately ship a smaller, typed surface; the diff is a backlog, not a
target.

This release mined the drawing-breadth, appearance, filtered-listing and ISO
drawing workflow gaps:
125 tools now (39 core / 86 extended). Already covered here: session/documents/
export/rebuild, materials, appearance, sketching (line, circle, arc, 3-point
arc, ellipse, rectangle, polygon, spline, slot, point, offset, convert, trim,
mirror, fillet, chamfer, construction toggle, edit/reopen, dimension read-back
and re-drive), extrude, cut, revolve, fillet, chamfer, shell, simple hole,
draft, sweep, loft, suppression, patterns, mirror, reference planes and axes,
inspection (faces, edges, bodies, vertices, mass properties, bounding box,
errors, measure, filters), assemblies (components, mates with read-back,
fix/float, interference), drawings (sheets, standard/projected/section/detail
views, view move/rescale/restyle/delete, in-view sketching, center marks and
centerlines, model dims, auto-dimension, picked-geometry dimensions, dimension
tolerances, datum tags, GD&T frames, surface finish, revision tables, assembly
BOM tables and balloons, hole callouts (Hole Wizard holes only), notes,
annotation move/delete/re-text with resolved links, ISO units/properties,
manifests, preflight and release validation), export.

Remaining gaps, roughly in value order:

1. `rib` — implemented here but withheld from the tool surface: `InsertRib`
   builds nothing on the SW2026 SP0.0 build under every documented combination
   (see COM-QUIRKS); re-probe on a later build.
2. Selection specs: point and `face_edges` specs (filtered face/edge listings
   are shipped), and mate editing / face-edge-pair mates by index (ours mates
   by component and outward direction).
3. Feature-level colour (this release ships model- and face-level
   `set_appearance`).

Areas where this server is ahead of the reference set: measured evidence from
every mutation (mass properties/bbox/What's Wrong), interference detection with
overlap volumes, move/rotate read-back verification, file checkpoints with
rollback, the sandboxed output root, the typed tier/catalog system,
`verify_export`, `get_capabilities`, appearance and view-state read-back, and
reference-axis/vertex/measure read-back.

## Other repositories to keep in view

- `autocad-mcp` (limuzi013) — sibling project by the Slacker-LLC author; useful
  for cross-CAD tool-convention decisions.
- czuryk's transaction/idempotency design notes are the main reference for the
  planned batch/plan-execution milestone.
