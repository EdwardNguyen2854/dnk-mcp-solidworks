# Plan: Make Projected Drawing Views the Default

**Status:** Proposed; implementation not started  
**Goal:** When creating an orthographic drawing, create one master model view and derive companion views from that same master with `drawing_insert_projected_view`.

## Findings

- The MCP server already provides `drawing_insert_projected_view`, and its description documents using one exact master `parent_view` for each companion.
- The projected-view tool schema currently makes `parent_view` optional, and the domain function can fall back to the first model view. This weakens the intended explicit-parent contract.
- The ISO drawing, dnk-solidworks-sheet-layout, and dnk-solidworks-drawing-acceptance skills already prescribe the master-then-projections workflow. Their model-invocation descriptions may not reliably surface it for generic 2D drawing requests.
- The `iso_flange_demo.py` and `drawing_smoke.py` examples use `drawing_insert_standard_views`, which inserts independent standard views. These examples may reinforce the behavior the workflow is intended to avoid.
- `acceptance_asm_drw.py` already contains live checks for two companions projected from the same master, including projected type, parent, placement, source model, and configuration.

## Proposed Work

1. **Harden the projected-view contract**
   - Make `parent_view` required in the `drawing_insert_projected_view` MCP schema.
   - Reject missing or blank parent names in the domain function instead of silently selecting the first model view.
   - Clarify tool descriptions: `drawing_insert_view` inserts the master; `drawing_insert_projected_view` creates orthographic companions from that exact master; `drawing_insert_standard_views` is an independent-view batch for callers who explicitly request it.
   - Preserve the existing direct-batch behavior and compatibility of `drawing_insert_standard_views`.

2. **Align examples with the preferred workflow**
   - Update `scripts/iso_flange_demo.py` to insert one front master, retain its returned/listed exact name, and create the top and right companions with `drawing_insert_projected_view`, passing the same `parent_view` each time.
   - Update `scripts/drawing_smoke.py` to exercise the master-plus-projections workflow rather than demonstrating independent standard-view insertion.
   - Keep any genuinely useful direct-batch coverage as an explicit separate test, not as the primary workflow example.

3. **Improve skill discovery and guidance**
   - Sharpen model-invocation descriptions for `dnk-solidworks-iso-engineering-drawing`, `dnk-solidworks-sheet-layout`, and `dnk-solidworks-drawing-acceptance` to include generic 2D/orthographic drawing and projected-view requests.
   - Put the master → projected companions sequence early in the relevant procedure and retain the requirement to pass the same exact master name every time.
   - Keep first-angle/third-angle placement, source/configuration verification, and the direct-batch exception consistent across skills, `docs/ISO-DRAWING.md`, and `AGENTS.md`.

4. **Add regression coverage**
   - Add a unit test asserting that omitting `parent_view` is rejected by the registered MCP tool contract before any COM call.
   - Retain or strengthen live acceptance assertions that each companion is projected, reports the same master parent, and resolves to the expected source model and configuration.

## New-Tool Decision

No new COM tool is planned initially: the existing projected-view tool already performs the required operation, and live acceptance code covers multiple projections from one master. If agents continue creating standalone orthographic views after the contract, example, and skill changes, evaluate a dedicated one-call orthographic-set helper. Any such helper must compose one master insertion followed by projected companions; it must not create independent views as a substitute.

## Verification and Gate

- Run unit tests: `python -m pytest tests/unit -q`.
- Inspect the registered tool schema with `python -m solidworks_mcp --list-tools` and confirm `parent_view` is required.
- With a running SOLIDWORKS 2026 session, confirm attach/capabilities with `python -m solidworks_mcp --check`, then run `python scripts/acceptance_asm_drw.py drawing_tools` and the updated drawing demo.
- Live checks require an available SOLIDWORKS session. If it is unavailable, record live verification as blocked; do not infer a pass from historical results.
- Review the final diff and confirm the skills, examples, tool contract, and docs all describe the same workflow.
