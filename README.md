# dnk-mcp-solidworks

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](#requirements)
[![CI](https://github.com/EdwardNguyen2854/dnk-mcp-solidworks/actions/workflows/ci.yml/badge.svg)](https://github.com/EdwardNguyen2854/dnk-mcp-solidworks/actions/workflows/ci.yml)

An open-source **Model Context Protocol (MCP) server** that lets an AI agent
design, measure, and verify real parametric **SOLIDWORKS** parts, assemblies,
and drawings inside a **running SOLIDWORKS session** — through the documented
COM API, with measured evidence for every change.

It does not launch SOLIDWORKS, does not register an add-in, does not execute
arbitrary code, and does not touch the network in its default stdio mode. It
attaches to the session you already have open and calls the same API a macro
would, so if a tool cannot do something, neither could a macro.

> **Project status:** beta (`0.1.0`). Validated against **SOLIDWORKS 2026 SP0.0**
> (typelib 34.0) on Windows. Other releases may behave differently; the server
> probes capabilities at runtime and fails loudly when a build disagrees.

```
MCP client ──stdio──► server (async) ──► one STA COM worker thread ──► SOLIDWORKS
                        │
                        ├─ registry: typed tools, tiers, validation
                        ├─ domain: sketch, features, inspect, assemblies, drawings
                        └─ transactions: checkpoints, rollback, evidence
```

## Why this server

**1. Every mutation returns measured evidence.** A boss extrude does not report
"success"; it reports volume, mass, bounding box, rebuild state, and
SOLIDWORKS' What's Wrong list. Success is execution evidence, never proof.

**2. Explicit units and declarative selection.** Every length parameter ends in
`_mm` and every angle in `_deg`; conversion to the API's metres/radians happens
once, at the boundary. Geometry is chosen by indices from `list_faces` /
`list_edges` / `list_sketch_segments`, never by the implicit global selection
set.

**3. Fail loud, and never trust the API's return values.** Tools return
`{"ok": false, "error": {code, message, hint, recoverable}}` with actionable
hints. Feature success is judged by rebuild + `GetWhatsWrong` + measured
geometry — the same API returns null, `False`, or stale values in equal measure
(see [`docs/COM-QUIRKS.md`](docs/COM-QUIRKS.md)).

## Highlights

- **Part modelling** — sketch on planes or planar faces; lines, circles, arcs,
  ellipses, rectangles, polygons, splines, slots, points; relations, driving
  dimensions with read-back and re-drive, offset, convert, trim, fillet,
  chamfer, mirror, construction toggle, sketch re-editing; boss/cut extrude
  (including `through_all_both`), revolve/revolve-cut, thin extrudes,
  constant/face fillets, chamfer variants, shell, simple/counterbore/
  countersink/tapped holes, cosmetic threads, dome, draft, sweep, loft, feature
  suppression, materials; reference planes and axes; linear and circular
  patterns; mirror.
- **Closed-loop verification** — mass properties, bounding box, What's Wrong,
  feature/face/edge/body/vertex listings, point-to-point and face measurement,
  and a screenshot returned as image content so the agent can look at what it
  built.
- **Assemblies** — insert components with deterministic origin placement,
  move/rotate with read-back verification, mate planar faces by direction, read
  mates back, fix/float components, detect interference with overlap volumes.
- **Drawings** — create a drawing from a model, manage sheets, insert standard,
  projected, section, and detail views, move/rescale/restyle views, sketch in a
  view, add center marks and centerlines, import model dimensions, generate
  DimXpert auto-dimensions, add notes, set dimension tolerances (symmetric,
  bilateral, limits, ISO fits), add datum tags, geometric tolerance frames, and
  surface finish symbols, insert revision tables, add assembly BOM tables and
  auto-balloons, attempt hole callouts, manage ISO title-block properties,
  collect a drawing manifest, validate observable ISO state, read every
  annotation back, and export PDF/DXF.
- **Transactions** — file checkpoints with debounce, listing, and rollback.
- **Export** — STEP, IGES, STL, 3MF, Parasolid, PDF, DXF, DWG, images, with
  file-existence and size verification plus structural verification of the
  written artifact (PDF pages, DXF entities and extents, STL triangles).
- **Tiered tool surface** — `core` / `extended` / `advanced` / `debug` and a
  `search_tools` meta-tool, so the agent's tool selection stays accurate.

## Requirements

- Windows 10/11
- SOLIDWORKS **installed, licensed, and running** (tested against SOLIDWORKS
  2026 SP0.0, typelib 34.0)
- Python 3.11+ (3.12 tested)

## Quick start

```powershell
git clone https://github.com/EdwardNguyen2854/dnk-mcp-solidworks.git
cd dnk-mcp-solidworks
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Start SOLIDWORKS first, then point your MCP client at the entry point.

**opencode** (`opencode.json`):

```json
{
  "mcp": {
    "solidworks": {
      "type": "local",
      "command": ["D:/path/to/dnk-mcp-solidworks/.venv/Scripts/python.exe", "-m", "solidworks_mcp"],
      "environment": { "SW_MCP_TOOL_TIER": "extended" }
    }
  }
}
```

**Claude Code**:

```powershell
claude mcp add solidworks -- D:\path\to\.venv\Scripts\python.exe -m solidworks_mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "D:\\path\\to\\dnk-mcp-solidworks\\.venv\\Scripts\\python.exe",
      "args": ["-m", "solidworks_mcp"],
      "env": { "SW_MCP_TOOL_TIER": "extended" }
    }
  }
}
```

Call `get_capabilities` first: it reports the live SOLIDWORKS revision, the
typelib binding, discovered templates, and the active policy.

### ToolHive

ToolHive normally runs MCP servers in containers. This server cannot run inside
that container because it must share the Windows host process/session with the
already-running SOLIDWORKS application. Use the opt-in loopback HTTP adapter
instead; the COM worker remains in this Python process and ToolHive only proxies
MCP traffic to it.

Install the HTTP extra, start SOLIDWORKS, and run the host process in one
PowerShell window:

```powershell
python -m pip install -e ".[dev,toolhive]"
python -m solidworks_mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Before registering a workload, start Docker Desktop (or another
Docker-compatible runtime), because ToolHive requires an available container
runtime for its workload manager. If the ToolHive CLI is not on `PATH`, open a
new PowerShell window or add its installed location for the current window:

```powershell
$env:Path += ";$env:LOCALAPPDATA\ToolHive\bin"
thv version
```

In a second PowerShell window, register the host endpoint with ToolHive:

```powershell
thv run --name solidworks --transport streamable-http --proxy-port 8766 `
  http://127.0.0.1:8765/mcp
```

Then use `thv list` to see the ToolHive proxy and connect your AI client to that
proxy. To inspect the tools directly:

```powershell
thv mcp list tools --server http://127.0.0.1:8766/mcp
```

The ToolHive UI uses the same values under **Add remote MCP server**:
`http://127.0.0.1:8765/mcp`, transport **Streamable HTTP**, and no
authentication. The endpoint binds to loopback only and the default stdio
transport is unchanged.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SW_MCP_TOOL_TIER` | `extended` | `core`, `extended`, `advanced`, `debug`, `all` |
| `SW_MCP_OUTPUT_ROOT` | `~/Documents/dnk-mcp-solidworks` | Every file the server writes stays under here |
| `SW_MCP_ALLOWED_ROOTS` | unset | Extra writable roots, `;`-separated |
| `SW_MCP_TEMPLATE_DIR` | auto-discovered | Folder with `.prtdot`/`.asmdot`/`.drwdot` |
| `SW_MCP_SLDWORKS_EXE` | unset | `SLDWORKS.exe` path (typelib fallback) |
| `SW_MCP_AUTO_CHECKPOINT` | `1` | Checkpoint before risky mutations |
| `SW_MCP_CHECKPOINT_DEBOUNCE_SEC` | `45` | Minimum seconds between checkpoints |
| `SW_MCP_OPERATION_TIMEOUT_SEC` | `180` | Per-call COM timeout |
| `SW_MCP_LOG_LEVEL` | `INFO` | Log level (`%LOCALAPPDATA%\dnk-mcp-solidworks\server.log`) |
| `SW_TYPELIB_MAJOR` / `SW_TYPELIB_MINOR` | auto | Force a typelib version |

Machine-specific overrides can also live in a gitignored `config.local.json`.

## Safety

- **Agent-autonomous by default**: auto-checkpoint before destructive
  operations, auto-verify after every mutation, no per-operation confirmation.
- Hard saves, overwrites, and document close-without-save are explicit tool
  calls; closing without saving reports that unsaved changes were discarded.
- Paths outside the allowed roots are refused for every write; reading an
  existing file is allowed anywhere.
- A dedicated STA thread serialises all COM calls; a per-call timeout marks a
  blocked worker instead of hanging the server.
- A modal-dialog guard disables `swInputDimValOnCreate` around dimension
  creation — on this build leaving it on crashes the session.

> **Before running live acceptance suites, save your open work.** They attach to
> your session and create/close their own documents (discard, never save), but a
> crash in SOLIDWORKS cannot be undone.

## Workflow skills

The tool catalog is the capability layer; `skills/<name>/SKILL.md` carries the
procedure layer (order of operations, defaults, stop conditions) that turns the
tools into a repeatable workflow. The bundled pack is:

- `dnk-solidworks-iso-engineering-drawing`
- `dnk-solidworks-cad-house-standard`
- `dnk-solidworks-drawing-acceptance`
- `dnk-solidworks-sheet-layout`
- `dnk-solidworks-cad-remodel`
- `dnk-solidworks-image-assisted-modeling`

Install them into the directory your agent client scans:

```powershell
python -m solidworks_mcp --install-skill "D:\path\to\agent\skills"
```

Keep the skill and the server in sync: the skill names the tools it calls. For
drawing images, `view_reference_image` returns a local PNG/JPEG as image
content; image interpretation remains with the agent. The tool does not OCR,
trace, calibrate scale, or reconstruct geometry.

## Tool surface

Run `python -m solidworks_mcp --list-tools` for the authoritative catalog.
**143 tools** across the default profile (46 `core`, 97 `extended`):

| Domain | Examples |
|---|---|
| Session / documents | `get_status`, `get_capabilities`, `new_document`, `open_document`, `save_document`, `close_document`, `search_tools`, `set_file_property` |
| Sketch | `create_sketch`, `edit_sketch`, `list_sketches`, `sketch_rectangle`, `sketch_circle`, `sketch_line`, `sketch_arc`, `sketch_arc_3point`, `sketch_ellipse`, `sketch_slot`, `sketch_point`, `sketch_polygon`, `sketch_spline`, `sketch_trim`, `sketch_fillet`, `sketch_chamfer`, `sketch_mirror`, `sketch_construction`, `sketch_offset`, `sketch_convert_entities`, `sketch_add_dimension`, `sketch_add_relation`, `list_sketch_segments`, `list_dimensions`, `set_dimension` |
| Features | `boss_extrude`, `cut_extrude`, `revolve`, `revolve_cut`, `thin_extrude`, `fillet`, `chamfer`, `shell`, `simple_hole`, `counterbore_hole`, `countersink_hole`, `tapped_hole`, `cosmetic_thread`, `dome`, `draft`, `sweep`, `loft`, `set_feature_suppression`, `linear_pattern`, `circular_pattern`, `mirror_feature`, `set_material`, `set_appearance`, `rename_feature`, `delete_feature` |
| Reference geometry | `create_reference_plane`, `create_axis`, `list_reference_planes` |
| Inspection | `list_features`, `inspect_editable_features`, `list_faces`, `list_edges`, `list_bodies`, `list_vertices`, `measure`, `get_mass_properties`, `get_bounding_box`, `compare_model_geometry`, `check_errors`, `get_selection`, `resolve_entity_reference`, `highlight_entities` |
| View / export | `set_view`, `capture_screenshot`, `view_reference_image`, `export_document`, `verify_export` |
| Assemblies | `insert_component`, `list_components`, `set_component_transform`, `set_component_fixed`, `add_mate`, `list_mates`, `check_interference`, `get_assembly_bounding_box` |
| Drawings | `new_drawing`, `drawing_set_iso_units`, `drawing_set_sheet_format`, `list_drawing_sheets`, `drawing_add_sheet`, `drawing_activate_sheet`, `drawing_insert_view`, `drawing_insert_standard_views`, `drawing_insert_projected_view`, `drawing_insert_section_view`, `drawing_insert_detail_view`, `drawing_activate_view`, `drawing_set_view`, `drawing_create_sketch`, `drawing_insert_center_marks`, `drawing_insert_centerlines`, `list_drawing_views`, `list_drawing_view_edges`, `drawing_insert_model_dimensions`, `drawing_auto_dimension`, `drawing_arrange_dimensions`, `drawing_add_dimension`, `list_drawing_dimensions`, `drawing_audit_feature_coverage`, `drawing_set_dimension_tolerance`, `drawing_insert_general_tolerance_table`, `drawing_insert_datum`, `drawing_insert_gtol`, `drawing_insert_surface_finish`, `drawing_insert_revision_table`, `drawing_add_revision`, `drawing_insert_bom_table`, `drawing_insert_balloons`, `drawing_insert_hole_callout`, `drawing_add_note`, `list_drawing_annotations`, `drawing_update_annotations`, `drawing_move_annotation`, `drawing_delete_annotation`, `drawing_set_annotation_text`, `drawing_delete_view`, `list_drawing_properties`, `drawing_set_property`, `drawing_manifest`, `drawing_layout_audit`, `drawing_preflight`, `validate_iso_drawing` |
| Transactions | `create_checkpoint`, `list_checkpoints`, `rollback_to_checkpoint` |

## Testing

```powershell
# unit layer, no SOLIDWORKS required
python -m pytest tests/unit

# live acceptance: needs a running SOLIDWORKS session
python scripts/mcp_smoke.py                       # MCP over stdio, box volume vs hand calc
python scripts/acceptance.py                      # 43 part-geometry checks
python scripts/acceptance_modelling_depth.py      # 26 feature-depth checks
python scripts/acceptance_combine_bodies.py       # 26 combine-body checks
python scripts/acceptance_asm_drw.py              # 68 assembly + drawing checks
python scripts/acceptance_asm_drw.py drawing_tools  # run one named group only
python scripts/acceptance_iso_annotations.py      # 50 ISO annotation checks
python scripts/acceptance_drawing_edit.py         # 28 annotation/checkpoint checks
python scripts/acceptance_selection.py            # selection reference checks
python scripts/acceptance_reliability.py          # precision/rollback/comparison checks
python scripts/iso_drawing_demo.py                # end-to-end ISO drawing demo
python scripts/iso_flange_demo.py                 # revolved flange + full ISO A3 drawing, 76 checks
```

Every live check compares measured geometry (volume, position, interference
volume, bounding box, DXF extents) against hand calculations, not against "it
looked fine". Exploratory, single-use API probes live in
[`scripts/probes/`](scripts/probes/); the reusable typelib inspector is
`scripts/probe_api.py`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module map and threading model
- [`docs/COM-QUIRKS.md`](docs/COM-QUIRKS.md) — the measured API quirks this server works around
- [`docs/PRIOR-ART.md`](docs/PRIOR-ART.md) — the public reference servers and what was learned from each
- [`docs/ISO-DRAWING.md`](docs/ISO-DRAWING.md) — ISO metric drawing profile, workflow, and validation
- [`docs/adr/0001-binding-strategy.md`](docs/adr/0001-binding-strategy.md) — why early binding and interface wrapping
- [`AGENTS.md`](AGENTS.md) — contributor/agent rules for changing the server
- [`scripts/probe_api.py`](scripts/probe_api.py) — inspect the installed typelib (`--method`, `--enum`, `--search`, `--brief`)

## Roadmap

- Selection specs: point and `face_edges` specs, and mate editing / face-pair
  mates by index
- Hole callouts: the tool refuses holes without callout data on SW2026 SP0.0
  (verified on `SimpleHole2`, sketch-cut, and practice-part holes); verify with
  a Hole Wizard part. `IFeatureManager.HoleWizard5` exists on this typelib but
  created no feature under every tested parameter set, and the session crashed
  in `mfc140u.dll` during that probing — re-probe carefully on a fresh session
- `rib` (measured: `InsertRib` builds nothing on this SW2026 SP0.0 build;
  re-probe on a later build)
- Equations and configurations; model-state diffing and section probes
- Batch/plan execution and richer idempotency accounting

## Citation

If you use this software in academic work or a published project, cite it using
[`CITATION.cff`](CITATION.cff):

```bibtex
@software{nguyen_dnk_mcp_solidworks_2026,
  author  = {Nguyen, Edward},
  title   = {dnk-mcp-solidworks},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/EdwardNguyen2854/dnk-mcp-solidworks},
  license = {Apache-2.0}
}
```

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`AGENTS.md`](AGENTS.md) before opening a pull request: the architecture rules
(single STA COM thread, typed interface wrapping, explicit units, measured
evidence) are not optional. Security reports go through
[`SECURITY.md`](SECURITY.md), never a public issue.

## License and attribution

Copyright 2026 **Edward Nguyen**. Licensed under the
[Apache License 2.0](LICENSE).

You may use, test, modify, fork, and redistribute this project — including
commercially — **provided you credit the original author**. In practice that
means:

- keep `LICENSE` and [`NOTICE`](NOTICE) intact in every copy, fork, and
  distribution;
- retain the copyright and attribution notices;
- state prominently that you changed modified files;
- credit **Edward Nguyen** and link back to
  <https://github.com/EdwardNguyen2854/dnk-mcp-solidworks> in your README,
  documentation, or about screen.

See [`NOTICE`](NOTICE) for the exact attribution requirement and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the open-source projects
whose documented patterns informed this clean-room implementation.

SOLIDWORKS is a trademark of Dassault Systèmes. This project is not affiliated
with or endorsed by Dassault Systèmes.
