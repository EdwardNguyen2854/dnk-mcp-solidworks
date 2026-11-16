# dnk-mcp-solidworks

**dnk**'s private, best-of-class MCP server that drives a **running SOLIDWORKS
session** through its COM API — built for an AI agent to design, measure and
verify real parametric parts, assemblies and drawings.

It does not launch SOLIDWORKS, does not register an add-in, does not execute
arbitrary code and does not touch the network. It attaches to the session you
already have open and calls the documented API, so if a tool cannot do
something, neither could a macro.

```
MCP client ──stdio──► server (async) ──► one STA COM worker thread ──► SOLIDWORKS
                        │
                        ├─ registry: typed tools, tiers, validation
                        ├─ domain: sketch, features, inspect, assemblies, drawings
                        └─ transactions: checkpoints, rollback, evidence
```

## The three ideas that make it usable

**1. Every mutation returns measured evidence.** A boss extrude does not report
"success"; it reports volume, mass, bounding box, the rebuild state and
SOLIDWORKS' What's Wrong list. Success is execution evidence, never proof.

**2. Explicit units and declarative selection.** Every length parameter ends in
`_mm` and every angle in `_deg`; conversion to the API's metres/radians happens
once, at the boundary. Geometry is chosen by indices from `list_faces` /
`list_edges` / `list_sketch_segments`, never by the implicit global selection
set.

**3. Fail loud, and never trust the API's return values.** Tools return
`{"ok": false, "error": {code, message, hint, recoverable}}` with actionable
hints. Feature success is judged by rebuild + `GetWhatsWrong` + measured
geometry — the same API returns null, False or stale values in equal measure
(see `docs/COM-QUIRKS.md`).

## Highlights

- **Part modelling loop** — sketch on planes or planar faces; lines, circles,
  arcs (centre and 3-point), ellipses, rectangles, polygons, splines, slots,
  points; relations, driving dimensions with read-back and re-drive, offset,
  convert, trim, fillet, chamfer, mirror, construction toggle, sketch
  re-editing; boss/cut extrude (including a corrected `through_all_both`),
  revolve/revolve-cut, thin extrudes, constant/face fillets, chamfer variants,
  shell, simple/counterbore/countersink/tapped holes, cosmetic threads, dome,
  draft, sweep, loft, feature
  suppression, materials; reference planes and axes; linear and circular
  patterns; mirror.
- **Closed-loop verification** — mass properties, bounding box, What's Wrong,
  feature/face/edge/body/vertex listings, point-to-point and face measurement,
  and a screenshot returned as image content so the agent can look at what it
  built.
- **Assemblies** — insert components with deterministic origin placement,
  move/rotate with read-back verification, mate planar faces by direction, read
  mates back, fix/float components, detect interference with overlap volumes.
- **Drawings** — create a drawing from a model, manage sheets (list/add/
  activate, paper size and scale), insert standard, projected, section and
  detail views, move/rescale/restyle views, sketch in a view, add center marks
  and centerlines, import model dimensions, generate DimXpert
  auto-dimensions, add notes, set dimension tolerances (symmetric, bilateral,
  limits, ISO fits), add datum tags, geometric tolerance frames and surface
  finish symbols, insert revision tables, add assembly BOM tables and
  auto-balloons, attempt hole callouts (Hole Wizard holes), manage ISO
  title-block properties, collect a drawing manifest, validate observable ISO
  state, read every annotation back, export PDF/DXF.
- **Transactions** — file checkpoints with debounce, listing and rollback.
- **Export** — STEP, IGES, STL, 3MF, Parasolid, PDF, DXF, DWG, images, with
  file-existence and size verification, plus structural verification of the
  written artifact (PDF pages, DXF entities and extents, STL triangles).
- **Tiered tool surface** — `core` / `extended` / `advanced` / `debug` and a
  `search_tools` meta-tool, so the agent's tool selection stays accurate.

## Requirements

- Windows 10/11
- SOLIDWORKS **installed, licensed and running** (tested against the
  SOLIDWORKS 2026 SP0.0 typelib, version 34.0)
- Python 3.11+ (3.12 tested)

## Install

```powershell
git clone <this repo> dnk-mcp-solidworks
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
typelib binding, discovered templates and the active policy.

### ToolHive

ToolHive normally runs MCP servers in containers. This server cannot run inside
that container because it must share the Windows host process/session with the
already-running SOLIDWORKS application. Use the opt-in loopback HTTP adapter
instead; the COM worker remains in this Python process and ToolHive only
proxies MCP traffic to it.

Install the HTTP extra, start SOLIDWORKS, and run the host process in one
PowerShell window:

```powershell
python -m pip install -e ".[dev,toolhive]"
python -m solidworks_mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Before registering a workload, start Docker Desktop (or another
Docker-compatible runtime). ToolHive requires an available container runtime
for its workload manager. If the ToolHive CLI is not on `PATH`, open a new
PowerShell window or add its installed location for the current window:

```powershell
$env:Path += ";$env:LOCALAPPDATA\ToolHive\bin"
thv version
```

In a second PowerShell window, register the host endpoint with ToolHive:

```powershell
thv run --name solidworks --transport streamable-http --proxy-port 8766 `
  http://127.0.0.1:8765/mcp
```

Then use `thv list` to see the ToolHive proxy and connect your AI client to
that proxy. To inspect the tools directly:

```powershell
thv mcp list tools --server http://127.0.0.1:8766/mcp
```

The ToolHive UI uses the same values under **Add remote MCP server**:
`http://127.0.0.1:8765/mcp`, transport **Streamable HTTP**, and no
authentication. The endpoint binds to loopback only and the default stdio
transport is unchanged. If `thv` is not found after installing ToolHive UI,
open a new PowerShell window so its `%LOCALAPPDATA%\ToolHive\bin` entry is
loaded.

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

Machine-specific overrides can also live in a gitignored
`config.local.json`.

## Safety

- **Agent-autonomous by default**: auto-checkpoint before destructive
  operations, auto-verify after every mutation, no per-operation confirmation.
- Hard saves, overwrites and document close-without-save are explicit tool
  calls; closing without saving reports that unsaved changes were discarded.
- Paths outside the allowed roots are refused for every write; reading an
  existing file is allowed anywhere.
- A dedicated STA thread serialises all COM calls; a per-call timeout marks a
  blocked worker instead of hanging the server.
- A modal-dialog guard disables `swInputDimValOnCreate` around dimension
  creation — on this build leaving it on crashes the session.

## Workflow skills

The tool catalog is the capability layer; `skills/<name>/SKILL.md` carries the
procedure layer (order of operations, defaults, stop conditions) that turns
the tools into a repeatable workflow. The bundled pack is
`dnk-solidworks-iso-engineering-drawing`, `dnk-solidworks-cad-house-standard`,
`dnk-solidworks-drawing-acceptance`, `dnk-solidworks-sheet-layout`,
`dnk-solidworks-cad-remodel` and `dnk-solidworks-image-assisted-modeling`.
Install them into the directory your agent client scans:

```powershell
python -m solidworks_mcp --install-skill "D:\path\to\agent\skills"
```

Keep the skill and the server in sync: the skill names the tools it calls.
For drawing images, `view_reference_image` returns a local PNG/JPEG as image
content; image interpretation remains with the agent. The tool does not OCR,
trace, calibrate scale or reconstruct geometry.

## Tool surface

Run `python -m solidworks_mcp --list-tools` for the authoritative catalog.
143 tools across the default profile (46 `core`, 97 `extended`):

| Domain | Examples |
|---|---|
| Session / documents | `get_status`, `get_capabilities`, `new_document`, `open_document`, `save_document`, `close_document`, `search_tools`, `set_file_property` (custom properties for title-block links) |
| Sketch | `create_sketch`, `edit_sketch`, `list_sketches`, `sketch_rectangle`, `sketch_circle`, `sketch_line`, `sketch_arc`, `sketch_arc_3point`, `sketch_ellipse`, `sketch_slot`, `sketch_point`, `sketch_polygon`, `sketch_spline`, `sketch_trim`, `sketch_fillet`, `sketch_chamfer`, `sketch_mirror`, `sketch_construction`, `sketch_offset`, `sketch_convert_entities`, `sketch_add_dimension`, `sketch_add_relation`, `list_sketch_segments`, `list_dimensions`, `set_dimension` |
| Features | `boss_extrude`, `cut_extrude`, `revolve`, `revolve_cut`, `thin_extrude`, `fillet`, `chamfer`, `shell`, `simple_hole`, `counterbore_hole`, `countersink_hole`, `tapped_hole`, `cosmetic_thread`, `dome`, `draft`, `sweep`, `loft`, `set_feature_suppression`, `linear_pattern`, `circular_pattern`, `mirror_feature`, `set_material`, `set_appearance`, `rename_feature`, `delete_feature` |
| Reference geometry | `create_reference_plane`, `create_axis`, `list_reference_planes` |
| Inspection | `list_features`, `inspect_editable_features`, `list_faces` (surface/normal/area filters), `list_edges` (trimmed endpoints and closed-edge state), `list_bodies`, `list_vertices`, `measure`, `get_mass_properties` (typed accuracy), `get_bounding_box` (exact extrema), `compare_model_geometry` (explicit caller tolerances), `check_errors` |
| View / export | `set_view`, `capture_screenshot`, `view_reference_image` (local PNG/JPEG input as image content; absolute local paths or output-root-relative paths; bounded size/resolution), `export_document`, `verify_export` |
| Assemblies | `insert_component`, `list_components`, `set_component_transform`, `set_component_fixed`, `add_mate`, `list_mates`, `check_interference`, `get_assembly_bounding_box` |
| Drawings | `new_drawing` (framed A3 default), `drawing_set_iso_units`, `drawing_set_sheet_format`, `list_drawing_sheets`, `drawing_add_sheet`, `drawing_activate_sheet`, `drawing_insert_view` (explicit model/configuration), `drawing_insert_standard_views`, `drawing_insert_projected_view`, `drawing_insert_section_view`, `drawing_insert_detail_view`, `drawing_activate_view`, `drawing_set_view`, `drawing_create_sketch`, `drawing_insert_center_marks`, `drawing_insert_centerlines`, `list_drawing_views`, `list_drawing_view_edges`, `drawing_insert_model_dimensions`, `drawing_auto_dimension`, `drawing_arrange_dimensions`, `drawing_add_dimension`, `list_drawing_dimensions` (stable state IDs), `drawing_audit_feature_coverage`, `drawing_set_dimension_tolerance`, `drawing_insert_general_tolerance_table`, `drawing_insert_datum`, `drawing_insert_gtol`, `drawing_insert_surface_finish`, `drawing_insert_revision_table`, `drawing_add_revision`, `drawing_insert_bom_table`, `drawing_insert_balloons`, `drawing_insert_hole_callout`, `drawing_add_note`, `list_drawing_annotations`, `drawing_update_annotations` (typed batch), `drawing_move_annotation`, `drawing_delete_annotation`, `drawing_set_annotation_text`, `drawing_delete_view`, `list_drawing_properties`, `drawing_set_property`, `drawing_manifest`, `drawing_layout_audit` (full-sheet text screening and revision-table bounds), `drawing_preflight`, `validate_iso_drawing` |
| Transactions | `create_checkpoint`, `list_checkpoints`, `rollback_to_checkpoint` |

## Testing

```powershell
# unit layer, no SOLIDWORKS required
python -m pytest tests/unit

# live acceptance: needs a running SOLIDWORKS session
python scripts/mcp_smoke.py            # MCP over stdio, box volume vs hand calc
python scripts/acceptance.py           # 43 geometry checks (fillet, shell, cut, revolve, dimensions, patterns, mirror, reference planes, arcs/slots/ellipses, trim/mirror/fillet/chamfer, hole, draft, sweep, loft, suppression, axis, measure)
python scripts/acceptance_modelling_depth.py # 26 Wave-1 3D feature checks vs hand calculations
python scripts/acceptance_asm_drw.py   # assembly + drawing checks (mates read-back, fix/float, interference, framed sheets, projected/section/detail views, center marks, appearance, arranged dimensions, ISO properties/validation, PDF/DXF verification)
python scripts/acceptance_asm_drw.py drawing_tools  # run a named group only
python scripts/acceptance_iso_annotations.py        # ISO annotation suite (tolerances, datums/GD&T, surface finish, revision table)
python scripts/acceptance_drawing_edit.py           # annotation edit + picked-geometry dimensions + checkpoint/rollback
python scripts/acceptance_reliability.py            # precision diagnostics, real cut rollback, explicit-tolerance comparison
python scripts/iso_drawing_demo.py                  # end-to-end ISO drawing demo (closes its documents when done)
python scripts/iso_flange_demo.py                   # revolved flange housing part + full ISO A3 drawing, 76 checks
```

Every live check compares measured geometry (volume, position, interference
volume, bounding box, DXF extents) against hand calculations, not against "it
looked fine".

## Documentation

- `docs/ARCHITECTURE.md` — module map and threading model
- `docs/COM-QUIRKS.md` — the measured API quirks this server works around
- `docs/PRIOR-ART.md` — the public reference servers, what we learned from
  each, and what is still unmined
- `docs/ISO-DRAWING.md` — ISO metric drawing profile, workflow and validation
- `skills/dnk-solidworks-iso-engineering-drawing/SKILL.md` — reusable ISO drawing procedure
- `docs/adr/0001-binding-strategy.md` — why early binding and interface wrapping
- `scripts/probe_api.py` — inspect the installed typelib (`--method`,
  `--enum`, `--search`, `--brief`)

## Roadmap

- Selection specs: point and `face_edges` specs, and mate editing / face-pair
  mates by index
- Hole callouts: the tool refuses holes without callout data on SW2026 SP0.0
  (verified on `SimpleHole2`, sketch-cut and practice-part holes); verify with
  a Hole Wizard part. `IFeatureManager.HoleWizard5` exists on this typelib but
  created no feature under every tested parameter set, and the session crashed
  in `mfc140u.dll` during that probing — re-probe carefully on a fresh session
- `rib` (measured: `InsertRib` builds nothing on this SW2026 SP0.0 build; re-probe on a later build)
- Equations and configurations; model-state diffing and section probes
- Batch/plan execution and richer idempotency accounting

## License

Proprietary / private. See `THIRD_PARTY_NOTICES.md` for the open-source
projects this architecture learned from.
