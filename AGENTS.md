# AGENTS.md

Windows-only MCP server driving a **running** SOLIDWORKS session over COM. It never
launches SOLIDWORKS, never runs arbitrary code, and never touches the network.
Current test target: SOLIDWORKS 2026 SP0.0, typelib 34.0, Python 3.12.

## Repository

This is a public open-source project licensed under Apache-2.0 (Copyright 2026
Edward Nguyen). Keep `LICENSE` and `NOTICE` intact and preserve the attribution
requirement in `NOTICE` in every copy, fork, and distribution. Third-party
attribution lives in `THIRD_PARTY_NOTICES.md`.

Public docs are part of the deliverable. When behavior, setup, tool counts, or
paths change, update `README.md`, `CONTRIBUTING.md`, `scripts/README.md`,
`CHANGELOG.md`, the relevant `docs/` page, and the bundled skills in the same
change.

## Commands

```powershell
python -m pip install -e ".[dev]"          # editable install (deps already in system Python)
python -m pytest tests/unit -q             # unit tests, no SOLIDWORKS needed
python -m solidworks_mcp --list-tools      # tool catalog with tiers
python -m solidworks_mcp --check           # live capabilities (requires SOLIDWORKS)
python scripts/probe_api.py --method IFeatureManager FeatureExtrusion3 --brief
python scripts/probe_api.py --enum swEndConditions_e
python scripts/probe_api.py --search "WhatsWrong|SaveAs"
```

Live suites require SOLIDWORKS running and attach to the user's session. They
create/close their own documents (discard, never save), but warn the user to save
work first:

```powershell
python scripts/mcp_smoke.py            # MCP-over-stdio loop: part -> extrude -> measure
python scripts/probe_persist_reference.py    # entity identity: persist references + fingerprints
python scripts/acceptance_selection.py       # selection read / reference resolution / highlight tools
python scripts/acceptance.py           # 43 part-geometry checks vs hand calcs
python scripts/acceptance_modelling_depth.py # 26 Wave-1 feature-depth checks
python scripts/acceptance_combine_bodies.py  # 26 registered combine_bodies checks (add/subtract/common)
python scripts/acceptance_datum_selection.py # selection references, identity and owned highlights (disposable part)
python scripts/acceptance_datum_capture.py   # capture_screenshot current-view acceptance (disposable part)
python scripts/acceptance_asm_drw.py   # 68 assembly + drawing checks
python scripts/acceptance_asm_drw.py drawing_tools   # run one named group only
python scripts/acceptance_iso_annotations.py         # 50 ISO annotation checks
python scripts/acceptance_drawing_edit.py            # 28 annotation/checkpoint checks
python scripts/iso_flange_demo.py                    # flange part + full ISO A3 drawing, 76 checks
```

These scripts (not the unit tests) are the real verification. Every check compares
measured volume/position/interference against a hand calculation.

## Architecture rules (violating these breaks the server)

- **All COM access runs on the single STA worker thread** via `com/worker.run(fn)`.
  Never touch COM from the asyncio loop or a tool handler directly.
- **Wrap every raw dispatch**: `binding.wrap(obj, "IModelDoc2")`. `NewDocument`,
  `ActiveDoc` and `SelectionManager` return untyped `CDispatch` and fail late-bound.
- **Out parameters**: pass plain ints, never `VARIANT`; unpack with
  `session.com_result(result, n)`. Example: `SaveAs3(path, 0, 1, None, None, 0, 0)`.
- **Propget-with-args members** come back as bound methods; normalise with
  `binding.value(member)`.
- **Typed double arrays**: use `binding.r8_array([...])` + `IMathTransform.SetData`
  (rotation rows, translation, scale). Bare lists are mis-marshalled and silently
  rotate/zero vectors.
- **Units**: tool args are `_mm`/`_deg`; conversion only in `com/units.py` (COM is
  metres/radians). Note `GetTessTriangles(True)` for system units; `GetTessTriangles(False)`
  returns document units.
- **Selection**: indices come from `list_faces`/`list_edges`/`list_sketch_segments`,
  then `inspect.select_entity` (QueryInterface to `IEntity`, `Select4` + mark).
  Coordinate picking via `SelectByID2("", "FACE", x, y, z, ...)` is unreliable here.
- **Never trust feature return values**. Judge success by rebuild + `GetWhatsWrong`
  + measured mass properties (`inspect.rebuild`, `inspect.whats_wrong`). Some calls
  return `None`/`void` despite building (e.g. `InsertFeatureShell`).
- **Tool results use the envelope**: `ok(data, evidence=...)` or a raised
  `SwMcpError` subclass (`errors.py`). Mutations must include `evidence`.
- For a new orthographic drawing, create one master view with
  `drawing_insert_view`, then create each companion with
  `drawing_insert_projected_view`, passing the same exact master view name as
  `parent_view` every time. Use `drawing_insert_standard_views` only when a
  direct batch of model views is explicitly wanted. Insert projections before
  adding sheets, then verify view types, positions and source identity with
  `list_drawing_views`. On SW2026 projected views may omit orientation read-back;
  confirm the projection convention from the sheet setting, symbol and raster.
- Drawing view insertion requires an exact open `model_reference` and
  `configuration`; verify the resolved model identity from `list_drawing_views`.
  Live acceptance on typelib 34.0 reads `IView.ReferencedConfiguration` back;
  report it unavailable only when the installed binding's getter fails.
- Geometry-comparison success requires caller tolerances for volume, exact
  extrema, and sampled surface deviation. Report sample limits and topology;
  the surface metric is not an analytic Hausdorff proof.
- Screenshot results use MCP image content blocks. Keep image base64 out of the
  text JSON envelope and logs.

## SOLIDWORKS API workflow

- The published API docs disagree with the shipped typelib (argument counts,
  enum values). **Probe before coding**: `scripts/probe_api.py`.
- `docs/COM-QUIRKS.md` is the measured behavior log. Read it before touching
  binding, selection, transforms, assemblies or dimensions, and **update it** when
  you discover a new quirk.
- `docs/PRIOR-ART.md` maps the public reference servers to what we adopted and
  what is still unmined; check it before designing a new feature.
- Known traps already solved: modal `AddDimension2` crash (`swInputDimValOnCreate`
  toggle in `sketch.py`), `AddComponent5` needs the component pre-opened
  (`assemblies._open_component_if_needed`), `OpenDoc6` auto type fails (pass 1/2/3),
  mass-property density must be read before volume, `GetViews()` returns a nested tuple,
  single-ended `FeatureCut4` cuts need the `Dir` flag (with automatic direction
  retry), `InsertRefPlane` returns an untyped dispatch (use the tree diff),
  `InsertModelAnnotations3/4` behavior depends on document state/options
  (inventory annotations before and after); DimXpert `AutoDimension` works
  (`drawings.auto_dimension`), `SketchTrim` returns False on
  success (judge by the sketch fingerprint), `SimpleHole2` locates the hole from the
  face selection's `ISelectData` X/Y/Z (no sketch), `IComponent2.Select2` fails on
  mated components (use `GetSelectByIDString` + `SelectByID2`), `InsertRib`
  builds nothing on SW2026 SP0.0 (the `rib` tool is withheld; see COM-QUIRKS),
  reference extrudes require profile mark 0 + reference mark 1, thin features
  require the just-closed sketch to remain selected and `Dir=True`, chamfer
  type 16 is a no-op (use type 1 at 45 degrees for equal distance), cosmetic
  thread numeric args land as Diameter then BlindDepth despite typelib names,
  and `InsertDome` needs face mark 1,
  `CreateUnfoldedViewAt3` projects from the selected view and supports multiple
  projections on one drawing; it can return nothing once a second sheet exists,
  so add projections first. Drawing view sketches cannot be closed through
  the API (`exit_sketch` reports `view_sketch: true`), and
  `swCreateSectionViewAtOptions_e` has ExcludeFasteners=64 on this typelib.
  Annotation editing: `IAnnotation.Select3(True, None)` is dead on this build
  (use `Select(True)` + `DeleteSelection2`), `IDisplayDimension.SetText(0, ...)`
  is a no-op (prefix/suffix = 1/2), and `IAnnotation.GetTextFormat()` without an
  argument raises "Type mismatch" (use `INote.GetTextFormat()`), and
  `AddDimension2` on selected view edges creates readable dimensions
  (`drawing_add_dimension`).
  Datum tags snap their along-edge coordinate to the edge's start vertex (the
  free coordinate separates them), a surface-finish symbol stores its value
  but renders it at zero height (pair it with a `Ra x.x` note), and the
  revision table anchors its bottom-left at the frame's top-right corner
  (`Anchored=False` + reposition; the tools do this and report
  `inside_frame`).
  Drawings: a new sheet has no frame until `SetupSheet5` gets the paper code as
  `TemplateIn` (`.slddrt` paths and `LoadFile4` are ignored — `new_drawing`
  frames A3/ISO by default), `AutoDimension` dimensions the *selected* view
  (select before calling, or it picks another view), and its rows overlap
  until `drawing_arrange_dimensions` re-spaces them.
  Mates read back as `MateGroup` sub-features wrapped as `IMate2`
  (`assemblies.list_mates`).
- `HoleWizard5` exists but the exploratory call crashed in `mfc140u.dll` on
  SW2026 SP0.0; native Hole Wizard creation stays withheld until a safe
  acceptance path exists. Current compound holes are geometry-only. Drawing
  dimensions need an explicit feature coverage map when design-critical
  coverage is audited; edge counts never define feature quantity. The layout
  screen includes all returned text and exact revision-table bounds, while
  raster review remains the check for leaders, glyphs, frame geometry, and
  rendered overflow. House drawing skills use A3 landscape, first angle,
  millimetres, and revision A as review defaults. ISO 2768-2 is withdrawn and
  replaced by ISO 22081:2021; avoid the combined ISO 2768-mK note and an
  unspecified surface finish.
- An API-created section view needs its cutting line in the view sketch's
  **local** space (the view's centre, no scale factor): `drawing_insert_section_view`
  converts from sheet millimetres and verifies the cut by read-back, so a
  silent uncut section is no longer possible; the detail-view circle goes
  through the same conversion (see COM-QUIRKS).
- If a crash leaves SOLIDWORKS on the splash screen, a MyPDM dialog is blocking it;
  click "No, disable MyPDM" (see COM-QUIRKS).
- pywin32's makepy cache lives in `%TEMP%\gen_py` and is regenerated by
  `binding.get_module()`; delete it if binding gets into a bad state.
- Defaults: templates under `C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates`,
  write sandbox `~/Documents/dnk-mcp-solidworks` (tests override via
  `SW_MCP_OUTPUT_ROOT`), checkpoints in `%LOCALAPPDATA%\dnk-mcp-solidworks`.

## Conventions

- Tools: decorate with `@registry.tool` in `tools/{core,extended,advanced,debug}.py`,
  schemas via `registry.obj/number/string/...`. Tier default is `extended`
  (`SW_MCP_TOOL_TIER`). Keep the surface typed and fixed — no generic COM-invoke tool.
- Version-guard risky behavior on `capabilities`/typelib findings instead of assuming
  another SOLIDWORKS build behaves the same.
- No linter/formatter configured; match existing style (docstrings explain "why",
  inline comments only for quirks).
- Docs/scripts/README are part of the deliverable; keep them in sync when behavior
  changes. `docs/adr/0001-binding-strategy.md` explains the binding choice.

## Shell notes (win32 / PowerShell 5.1)

- No `&&` and no bash heredocs; chain with `;` or `cmd1; if ($?) { cmd2 }` and use
  one-line `python -c "..."` for quick checks.
- Prefer `workdir` over `cd`; quote Windows paths with backticks or doubles.
