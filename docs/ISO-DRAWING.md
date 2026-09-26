# ISO drawing workflow

The server's first engineering-drawing profile is `iso_metric`. It targets a
metric part drawing using ISO A4-A0 paper sizes, a stock ISO frame, and
first-angle projection by default.

The profile is intentionally a contract, not a claim of complete standards
compliance. The relevant drafting families include ISO 128, ISO 129-1, ISO
5455, ISO 5457, ISO 7200, and ISO 1101. Company title blocks, tolerance
policies, material conventions, and release procedures still need approval.

## Tool workflow

1. `drawing_preflight` checks the active drawing before release-only content is
   present.
2. `drawing_set_iso_units` forces and verifies millimetre document units when an
   existing drawing was not created through `new_drawing`.
3. `drawing_set_property` writes title-block-linked custom properties and reads
   them back.
4. `list_drawing_annotations` reports each annotation with a stable per-view
   index, the dimension `reading` (value with prefix/suffix) and a note's
   `resolved_text` for `$PRP` links. `drawing_move_annotation`,
   `drawing_delete_annotation` and `drawing_set_annotation_text` move, delete
   and re-text notes and dimensions (dimension prefix/suffix; note height is
   verified). `drawing_add_dimension` dimensions picked view edges from
   `list_drawing_view_edges`, and `drawing_delete_view` removes a view that
   landed in the wrong place.
5. `list_drawing_dimensions` + `drawing_set_dimension_tolerance` place ISO
   dimension tolerances (symmetric, bilateral, limits, min/max, hole/shaft
   fits) and verify the measured read-back. The ISO 2768-mK default is a
   general tolerance note; `drawing_insert_general_tolerance_table` inserts
   the DimXpert table where the typelib supports it (parts/assemblies).
6. `list_drawing_view_edges` addresses view edges; `drawing_insert_datum` and
   `drawing_insert_gtol` attach datum tags and geometric tolerance frames
   with measured frame read-back.
7. `drawing_insert_surface_finish` adds a surface finish symbol with the
   roughness value read back from the symbol text.
8. `drawing_insert_revision_table` + `drawing_add_revision` add the sheet's
   revision table (stock columns ZONE/REV./DESCRIPTION/DATE/APPROVED).
9. Assembly drawings: `drawing_insert_bom_table` inserts the parts list
   (the view's referenced configuration is resolved automatically) and
   `drawing_insert_balloons` auto-balloons the components. Hole callouts
   (`drawing_insert_hole_callout`) work for holes that carry callout data —
   Hole Wizard holes; other holes are refused with an actionable hint.
10. `drawing_manifest` collects sheets, views, annotations, properties, and
    rebuild state.
11. `validate_iso_drawing` checks the observable ISO contract and returns
    structured errors and warnings.
12. `export_document` plus `verify_export` verifies the exported PDF or DXF
    structure (`page_count_consistent` flags a declared/actual page mismatch).

The reusable orchestration procedure is in
`skills/iso-engineering-drawing/SKILL.md`.

## Current scope

Implemented and verified by the release validator:

- ISO A4-A0 sheet-size check
- measured stock sheet-frame/template-code check
- metric document-unit check
- first- or third-angle projection check
- positive sheet-scale check
- minimum model-view count
- clean rebuild and `What's Wrong` check
- required custom-property check
- model-view bounds and overlap checks
- readable dimension presence (display text or the measured `IDimension.Value`)
- dimension tolerance types and values (symmetric, bilateral, limits, min/max,
  ISO fits) with measured read-back
- datum tags (label read-back), geometric tolerance frames (frame values and
  characteristic symbol read-back) and surface finish symbols (roughness text
  read-back)
- revision table with its current revision read back
- assembly BOM table (rows and item cells) and auto-balloon texts
- read-back of linked title-block note display; advisory by default because
  the stock ISO frame carries static notes with no property links, enable with
  `require_title_block_display=true` for a company frame that links them
- structured annotation counts

Not yet claimed as fully automated ISO compliance:

- semantic validation beyond measured read-back (datum/feature cross-checks,
  tolerance-policy coverage)
- hole callouts for non-Hole-Wizard holes (measured 2026-09-26:
  `AddHoleCallout`/`AddHoleCallout2` return nothing for `SimpleHole2`,
  sketch-cut and practice-part holes; the callout tool documents the
  requirement and refuses with a hint)
- Hole Wizard hole creation through COM (every tested `HoleWizard4`/`5`
  parameter set created no feature; the session later crashed in
  `mfc140u.dll`, so re-probe on a fresh session before relying on it)
- weld symbols (ISO 2553)
- general and feature-specific tolerance policy validation
- company-specific sheet artwork and title-block geometry
- visual review of line weights, fonts, symbols, and exported PDF content

On SOLIDWORKS 2026 SP0.0, arbitrary `.slddrt` sheet artwork is not reachable
through the tested COM path. The validator therefore treats the stock ISO frame
as observable frame state, not proof of company-template compliance.
