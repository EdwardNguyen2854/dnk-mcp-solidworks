# Scripts

All scripts run from the repository root with the project environment active.
Live scripts require SOLIDWORKS **running and licensed**, and attach to your
current session. They create and close their own documents without saving, but
**save your open work first** in case SOLIDWORKS crashes.

## Verification suites

These are the real acceptance tests; each check compares measured geometry
against a hand calculation.

| Script | Scope |
|---|---|
| `mcp_smoke.py` | MCP over stdio: part, extrude, measure |
| `acceptance.py` | 43 part-geometry checks |
| `acceptance_modelling_depth.py` | 26 feature-depth checks |
| `acceptance_combine_bodies.py` | 26 combine-body checks |
| `acceptance_asm_drw.py` | 68 assembly + drawing checks (accepts a group name) |
| `acceptance_iso_annotations.py` | 50 ISO annotation checks |
| `acceptance_drawing_edit.py` | 28 annotation/checkpoint checks |
| `acceptance_selection.py` | Selection references and owned highlights |
| `acceptance_datum_selection.py` | Datum reference identity and revalidation |
| `acceptance_datum_capture.py` | Current-view screenshot capture |
| `acceptance_reliability.py` | Precision, rollback, and comparison checks |
| `probe_persist_reference.py` | Entity identity fingerprints (17 checks) |

## Demos and utilities

| Script | Purpose |
|---|---|
| `iso_drawing_demo.py` | End-to-end ISO bracket drawing workflow |
| `iso_flange_demo.py` | Revolved flange housing + full ISO A3 drawing (76 checks) |
| `drawing_create.py`, `drawing_smoke.py` | Small drawing examples |
| `datum_fixture.py` | Builds the datum acceptance fixture |
| `cadgenbench_runner.py` | Artifact-level CADGenBench runner |
| `close_scratch_docs.py` | Close leftover scratch documents |
| `probe_api.py` | Inspect the installed SOLIDWORKS typelib |

## Probes (`scripts/probes/`)

One-off exploratory scripts that measured a specific API behavior. They are kept
as evidence for the findings in [`docs/COM-QUIRKS.md`](../docs/COM-QUIRKS.md) and
[`docs/ROADMAP-3D-MODELLING.md`](../docs/ROADMAP-3D-MODELLING.md); they are not
maintained as a stable interface.

Install the project editable before running any script:

```powershell
python -m pip install -e ".[dev]"
```
