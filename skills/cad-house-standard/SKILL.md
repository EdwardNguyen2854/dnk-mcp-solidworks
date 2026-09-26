---
name: cad-house-standard
description: Editable house-standard profile (sheet, projection, tolerances, title block, revisions) that every drawing task starts from.
---

# CAD house standard

The server ships an ISO metric default profile; this skill is where a shop's
own defaults live. Treat the profile table as the contract for every drawing
task: read it first, apply it, and ask before overriding it.

## House standard profile

Edit the values below once for your shop. Everything left as `server default`
follows `new_drawing` / `validate_iso_drawing`.

| Setting | Value |
|---|---|
| Paper size | A3 landscape (server default) |
| Projection | first angle (`first_angle=true`) |
| Scale policy | 1:1 when it fits; otherwise the largest whole `1:n` from `[2, 2.5, 5, 10]` that fits the frame |
| Dimension units / precision | millimetres, 2 decimals (drawing template default) |
| General tolerance | ISO 2768-mK note: `UNLESS OTHERWISE SPECIFIED: GENERAL TOLERANCES ISO 2768-mK` |
| Fit standard | ISO 286 hole-basis preferred (H7 shafts, h6/k6 fits) |
| Surface finish default | Ra 3.2 for machined faces unless the model says otherwise |
| Title block fields | `Title`, `DrawingNumber`, `Revision`, `Material`, `Scale`, `Projection`, `DrawnBy`, `CheckedBy`, `ApprovedBy` |
| Revision scheme | `A`, `B`, `C` ...; every revision gets a row in the sheet revision table |
| Note block | material, finish, deburr, general tolerance note; no GD&T or finish symbols disguised as notes |
| Output package | PDF (primary) + DXF (sheet geometry); file name `<DrawingNumber>_Rev<Revision>` |
| Release authority | human/company review; the server validates observable state only |

## Rules

1. Confirm the profile with the user the first time a new part is drawn; after
   that, apply it without asking and state which defaults were used.
2. A requested deviation (third angle, ANSI sheet, different tolerance class)
   overrides one row only; record it in the final report.
3. Never describe the stock ISO frame as a company title block. The frame,
   drafting standard, tolerances and annotations need human approval before
   release; `validate_iso_drawing` only proves observable state.
4. Keep `skills/iso-engineering-drawing/SKILL.md` as the procedure and this
   file as the values. If a value changes, change it here, not in the
   procedure.
5. When the shop's title block is not reachable through COM (custom `.slddrt`
   artwork is not supported on SW2026 SP0.0), say so and report which
   title-block properties were written and verified instead.
