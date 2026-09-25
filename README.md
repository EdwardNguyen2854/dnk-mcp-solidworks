# solidworks-mcp-core

A private, best-of-class MCP server that drives a **running SOLIDWORKS session**
through its COM API — built for an AI agent to design, measure and verify real
parametric parts, assemblies and drawings.

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
  arcs, rectangles, polygons, splines; relations, driving dimensions, offset,
  convert; boss/cut extrude (including a corrected `through_all_both`),
  revolve, fillet, chamfer, shell, materials.
- **Closed-loop verification** — mass properties, bounding box, What's Wrong,
  feature/face/edge/body listings, and a screenshot returned as image content
  so the agent can look at what it built.
- **Assemblies** — insert components with deterministic origin placement,
  move/rotate with read-back verification, mate planar faces by direction,
  detect interference with overlap volumes.
- **Drawings** — create a drawing from a model, insert standard views, list
  views, export PDF/DXF.
- **Transactions** — file checkpoints with debounce, listing and rollback.
- **Export** — STEP, IGES, STL, 3MF, Parasolid, PDF, DXF, DWG, images, with
  file-existence and size verification.
- **Tiered tool surface** — `core` / `extended` / `advanced` / `debug` and a
  `search_tools` meta-tool, so the agent's tool selection stays accurate.

## Requirements

- Windows 10/11
- SOLIDWORKS **installed, licensed and running** (tested against the
  SOLIDWORKS 2026 SP0.0 typelib, version 34.0)
- Python 3.11+ (3.12 tested)

## Install

```powershell
git clone <this repo> mcp-solidworks-core
cd mcp-solidworks-core
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
      "command": ["D:/path/to/mcp-solidworks-core/.venv/Scripts/python.exe", "-m", "solidworks_mcp"],
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
      "command": "D:\\path\\to\\mcp-solidworks-core\\.venv\\Scripts\\python.exe",
      "args": ["-m", "solidworks_mcp"],
      "env": { "SW_MCP_TOOL_TIER": "extended" }
    }
  }
}
```

Call `get_capabilities` first: it reports the live SOLIDWORKS revision, the
typelib binding, discovered templates and the active policy.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SW_MCP_TOOL_TIER` | `extended` | `core`, `extended`, `advanced`, `debug`, `all` |
| `SW_MCP_OUTPUT_ROOT` | `~/Documents/solidworks-mcp-core` | Every file the server writes stays under here |
| `SW_MCP_ALLOWED_ROOTS` | unset | Extra writable roots, `;`-separated |
| `SW_MCP_TEMPLATE_DIR` | auto-discovered | Folder with `.prtdot`/`.asmdot`/`.drwdot` |
| `SW_MCP_SLDWORKS_EXE` | unset | `SLDWORKS.exe` path (typelib fallback) |
| `SW_MCP_AUTO_CHECKPOINT` | `1` | Checkpoint before risky mutations |
| `SW_MCP_CHECKPOINT_DEBOUNCE_SEC` | `45` | Minimum seconds between checkpoints |
| `SW_MCP_OPERATION_TIMEOUT_SEC` | `180` | Per-call COM timeout |
| `SW_MCP_LOG_LEVEL` | `INFO` | Log level (`%LOCALAPPDATA%\MCP-Solidworks\server.log`) |
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

## Tool surface

Run `python -m solidworks_mcp --list-tools` for the authoritative catalog.
Roughly 60 tools across:

| Domain | Examples |
|---|---|
| Session / documents | `get_status`, `get_capabilities`, `new_document`, `open_document`, `save_document`, `close_document`, `search_tools` |
| Sketch | `create_sketch`, `sketch_rectangle`, `sketch_circle`, `sketch_line`, `sketch_polygon`, `sketch_spline`, `sketch_add_dimension`, `sketch_add_relation`, `list_sketch_segments` |
| Features | `boss_extrude`, `cut_extrude`, `revolve`, `fillet`, `chamfer`, `shell`, `set_material`, `rename_feature`, `delete_feature` |
| Inspection | `list_features`, `list_faces`, `list_edges`, `list_bodies`, `get_mass_properties`, `get_bounding_box`, `check_errors` |
| View / export | `set_view`, `capture_screenshot`, `export_document` |
| Assemblies | `insert_component`, `list_components`, `set_component_transform`, `add_mate`, `check_interference`, `get_assembly_bounding_box` |
| Drawings | `new_drawing`, `drawing_insert_view`, `drawing_insert_standard_views`, `list_drawing_views` |
| Transactions | `create_checkpoint`, `list_checkpoints`, `rollback_to_checkpoint` |

## Testing

```powershell
# unit layer, no SOLIDWORKS required
python -m pytest tests/unit

# live acceptance: needs a running SOLIDWORKS session
python scripts/mcp_smoke.py            # MCP over stdio, box volume vs hand calc
python scripts/acceptance.py           # 11 geometry checks (fillet, shell, cut, revolve, dimension)
python scripts/acceptance_asm_drw.py   # 17 assembly + drawing checks
```

Every live check compares measured geometry (volume, position, interference
volume, bounding box) against hand calculations, not against "it looked fine".

## Documentation

- `docs/ARCHITECTURE.md` (planned) — module map and threading model
- `docs/COM-QUIRKS.md` — the measured API quirks this server works around
- `docs/adr/0001-binding-strategy.md` — why early binding and interface wrapping
- `scripts/probe_api.py` — inspect the installed typelib (`--method`,
  `--enum`, `--search`, `--brief`)

## Roadmap

- Patterns and mirror features; equations and configurations
- Model-state diffing, section probes, native-geometry export verification
- Drawing dimensions and annotations; PDF/DXF round-trip checks
- Batch/plan execution and richer idempotency accounting

## License

Proprietary / private. See `THIRD_PARTY_NOTICES.md` for the open-source
projects this architecture learned from.
