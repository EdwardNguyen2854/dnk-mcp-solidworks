---
name: sheet-layout
description: Place drawing views and keep-out zones on an ISO sheet using measured outlines instead of guessed coordinates.
---

# Sheet layout

All coordinates are sheet millimetres from the **lower-left** corner, the same
convention as `drawing_set_view`, `drawing_add_dimension` and the annotation
positions. Never place a view from a screenshot measurement when
`list_drawing_views` can give you the outline.

## Sheet geometry (ISO 5457, verify against the measured sheet)

| Sheet | Size (mm) | Frame (mm) |
|---|---|---|
| A0-A3 | A3 = 420 x 297 | 20 mm filing margin on the binding side, 10 mm on the other three sides |
| A4 | 210 x 297 | 10 mm all around |

`list_drawing_sheets` reports the paper size and the sheet size in mm; the
stock frame applied by `new_drawing` already contains the border and the zone
grid, so treat the table as expected values and confirm with the measured
sheet size. The title block sits in the lower-right corner; its notes are part
of the `Sheet1` annotation list (the zone letters/numbers also live there), so
keep views and dimensions clear of the title-block cluster rather than of an
assumed rectangle.

## Standard orthographic set

`drawing_insert_standard_views` already places front, top and right views at
the sheet scale with a clear gap (default `front_mm=[240, 160]`, `gap_mm=20`)
and returns the layout it used. First angle puts the right view left of the
elevation, third angle puts it right; the tool applies the choice from
`new_drawing`'s `first_angle`.

If you place views manually:

1. `list_drawing_views` — collect every model view's `outline_mm`.
2. Build the keep-out list: sheet frame insets, the title-block cluster
   (from `list_drawing_annotations` on `Sheet1`), and every existing view
   outline inflated by the dimension band you will add later (allow at least
   35-40 mm on the sides that will carry dimensions).
3. Choose a free rectangle that fits the new view's projected size at the
   intended scale, with a 20-30 mm gap to neighbours.
4. `drawing_set_view` to place it, then re-list to confirm the measured
   `outline_mm` moved where you intended.
5. `drawing_preflight` — `view_bounds` catches off-sheet views,
   `view_overlap` catches collisions.

## Alignment rules

- Projected views share the front view's axis: top/bottom views share its
  x-centre, left/right views share its y-centre (the standard-views tool
  follows this).
- Detail views go to the nearest free corner; section views follow the
  cutting-line arrows.
- One view per projected direction; use `drawing_insert_projected_view` for
  anything else, and remember projections must be added before a second sheet
  exists.

## Dimension bands

`drawing_arrange_dimensions` re-spaces a view's linear dimensions into rows on
the side they already occupy. Before adding a new dimension with
`drawing_add_dimension`, reserve a band on the side the dimension line will
use; after adding, re-run `drawing_arrange_dimensions` or move individual
annotations with `drawing_move_annotation`, then re-check
`list_drawing_annotations` positions against the frame and the title block.
