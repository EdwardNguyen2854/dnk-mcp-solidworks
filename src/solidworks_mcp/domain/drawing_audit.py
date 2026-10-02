"""Annotation layout audit: estimated boxes, collisions and off-frame items.

SOLIDWORKS does not expose annotation text bounds, so the audit estimates a
box for every text-bearing annotation from its measured anchor position and
its text content, then reports:

- **collisions** between annotations (real overlaps and near-misses within
  ``min_gap_mm``), and
- **off-frame** items whose box leaves the frame's usable area.

The estimation is deliberately simple (character count x 0.62 of the text
height) and the result says so; it is a screening tool that catches the
layout defects a reviewer would otherwise find by eye, not a substitute for
the visual check.

Measured reference cases the audit is calibrated on: two datum tags whose
letter boxes sat 4.3 mm apart on the front view (collision), and a revision
table that used to straddle the frame's top border (off-frame).
"""
from __future__ import annotations

import math

from ..com import binding
from ..com import units
from . import drawings, session

# Annotation types with estimated text boxes. Mechanical marks (centre marks,
# centrelines, cosmetic threads) and tables are excluded: their positions are
# geometry anchors, not text anchors, and tables have their own fit check in
# drawing_insert_revision_table.
TEXT_ANNOTATIONS = {
    "note",
    "dimension",
    "datum_tag",
    "datum_target",
    "geometric_tolerance",
    "surface_finish",
    "weld_symbol",
    "custom_symbol",
}

FRAME_INSET_MM = 10.0
CHAR_WIDTH_FACTOR = 0.62
EDGE_BAND_MM = 0.0
TITLE_BLOCK_MARGIN_MM = 20.0


def rect_from_box(box_mm) -> tuple[float, float, float, float]:
    """(min_pt, max_pt) -> (x1, y1, x2, y2)."""
    return (
        float(box_mm[0][0]),
        float(box_mm[0][1]),
        float(box_mm[1][0]),
        float(box_mm[1][1]),
    )


def rect_overlap_area(first, second) -> float:
    x_overlap = min(first[2], second[2]) - max(first[0], second[0])
    y_overlap = min(first[3], second[3]) - max(first[1], second[1])
    if x_overlap <= 0.0 or y_overlap <= 0.0:
        return 0.0
    return x_overlap * y_overlap


def rect_gap(first, second) -> float:
    """Shortest distance between two rectangles (0 when they overlap)."""
    dx = max(first[0] - second[2], second[0] - first[2], 0.0)
    dy = max(first[1] - second[3], second[1] - first[3], 0.0)
    return math.hypot(dx, dy)


def estimate_size_mm(annotation: dict, text_height_mm: float) -> tuple[float, float]:
    """Estimated (width, height) of an annotation's text box in mm."""
    kind = annotation.get("type")
    if kind == "datum_tag":
        side = text_height_mm + 2.0
        return side, side
    if kind == "geometric_tolerance":
        values = [
            str(value)
            for value in (annotation.get("frame_values") or [])
            if str(value)
        ]
        width = text_height_mm * CHAR_WIDTH_FACTOR * (len(" ".join(values)) + 3) + 4.0
        return max(width, 12.0), text_height_mm * 2.0
    if kind == "note":
        text = str(annotation.get("resolved_text") or annotation.get("text") or "")
        lines = text.replace("\r\n", "\n").split("\n")
        longest = max((len(line) for line in lines), default=1)
        width = longest * text_height_mm * CHAR_WIDTH_FACTOR
        height = max(len(lines), 1) * text_height_mm * 1.5
        return max(width, text_height_mm), height
    text = str(annotation.get("reading") or annotation.get("text") or "")
    if not text and annotation.get("value") is not None:
        text = str(annotation["value"])
    width = max(len(text), 2) * text_height_mm * CHAR_WIDTH_FACTOR
    return max(width, text_height_mm), text_height_mm * 1.6


def point_in_rect(x: float, y: float, rect: list[float]) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def title_block_region(listed: dict) -> list[float] | None:
    """Bounding box of the sheet's property-linked notes, inflated a little.

    The stock frame's title-block cells are notes carrying ``$PRP``/
    ``$PRPSHEET`` links; their bounding box identifies the title-block area so
    the audit can skip its dense static/linked labels instead of reporting
    them as collisions.
    """
    positions = []
    for view in listed.get("views", []):
        for annotation in view.get("annotations", []):
            if annotation.get("type") != "note":
                continue
            # Plain notes can report their own text through
            # PropertyLinkedText; only real $PRP/$PRPSHEET links count.
            if "$PRP" not in str(annotation.get("property_linked_text") or ""):
                continue
            position = annotation.get("position_mm")
            if position and len(position) >= 2:
                positions.append((float(position[0]), float(position[1])))
    if not positions:
        return None
    xs = [item[0] for item in positions]
    ys = [item[1] for item in positions]
    return [
        min(xs) - TITLE_BLOCK_MARGIN_MM,
        min(ys) - TITLE_BLOCK_MARGIN_MM,
        max(xs) + TITLE_BLOCK_MARGIN_MM,
        max(ys) + TITLE_BLOCK_MARGIN_MM,
    ]


def audit_annotations(
    views: list[dict],
    sheet_size_mm: list[float],
    *,
    inset_mm: float | dict[str, float] = FRAME_INSET_MM,
    min_gap_mm: float = 2.0,
    text_height_mm: float = 3.5,
    edge_band_mm: float = EDGE_BAND_MM,
    title_block_region_mm: list[float] | None = None,
) -> dict:
    """Pure audit over a ``list_annotations`` result and a sheet size.

    Annotations whose centre sits in the border band (zone letters/numbers)
    or inside the title-block region are counted under ``skipped`` rather
    than audited: they belong to the sheet format, not the layout under
    review. Set ``edge_band_mm=0`` and pass no title-block region to audit
    everything.
    """
    width_mm = float(sheet_size_mm[0])
    height_mm = float(sheet_size_mm[1])
    if isinstance(inset_mm, dict):
        left = float(inset_mm.get("left", FRAME_INSET_MM))
        bottom = float(inset_mm.get("bottom", FRAME_INSET_MM))
        right = float(inset_mm.get("right", FRAME_INSET_MM))
        top = float(inset_mm.get("top", FRAME_INSET_MM))
    else:
        left = bottom = right = top = float(inset_mm)
    frame = (left, bottom, width_mm - right, height_mm - top)
    skipped = {"frame_decoration": 0, "title_block": 0}
    items = []
    for view in views:
        view_name = view.get("name")
        for annotation in view.get("annotations", []):
            if annotation.get("type") not in TEXT_ANNOTATIONS:
                continue
            position = annotation.get("position_mm")
            if not position or len(position) < 2:
                continue
            cx, cy = float(position[0]), float(position[1])
            if edge_band_mm > 0 and (
                min(cx, cy, width_mm - cx, height_mm - cy) < edge_band_mm
            ):
                skipped["frame_decoration"] += 1
                continue
            if title_block_region_mm and point_in_rect(
                cx, cy, title_block_region_mm
            ):
                skipped["title_block"] += 1
                continue
            width, height = estimate_size_mm(annotation, text_height_mm)
            if annotation.get("type") == "note":
                # SOLIDWORKS notes anchor at the top-left of the text block
                # (text flows right and down), unlike dimensions and symbols
                # whose reported position is their centre.
                box = (cx, cy - height, cx + width, cy)
            else:
                box = (
                    cx - width / 2.0,
                    cy - height / 2.0,
                    cx + width / 2.0,
                    cy + height / 2.0,
                )
            text = (
                annotation.get("resolved_text")
                or annotation.get("reading")
                or annotation.get("text")
                or annotation.get("label")
                or (
                    str(annotation["value"])
                    if annotation.get("value") is not None
                    else ""
                )
            )
            items.append(
                {
                    "view": view_name,
                    "index": annotation.get("index"),
                    "type": annotation.get("type"),
                    "text": str(text)[:40],
                    "position_mm": [round(cx, 2), round(cy, 2)],
                    "size_mm": [round(width, 2), round(height, 2)],
                    "box": box,
                    "duplicate_key": (
                        " ".join(str(text).casefold().split())
                        if annotation.get("type") == "note"
                        else None
                    ),
                }
            )

    duplicate_groups = []
    for item in items:
        key = item.get("duplicate_key")
        if key:
            group = next((group for group in duplicate_groups
                          if group[0]["duplicate_key"] == key
                          and math.dist(group[0]["position_mm"], item["position_mm"]) <= 0.1), None)
            if group is None:
                duplicate_groups.append([item])
            else:
                group.append(item)
    duplicate_notes = [
        {
            "text": group[0]["text"],
            "annotations": [
                {key: item[key] for key in ("view", "index", "position_mm")}
                for item in group
            ],
        }
        for group in duplicate_groups
        if len(group) > 1
    ]

    collisions = []
    for first_index, first in enumerate(items):
        for second in items[first_index + 1:]:
            overlap = rect_overlap_area(first["box"], second["box"])
            gap = rect_gap(first["box"], second["box"])
            if overlap <= 0.0 and gap > min_gap_mm:
                continue
            collisions.append(
                {
                    "kind": "overlap" if overlap > 0.0 else "near",
                    "overlap_area_mm2": round(overlap, 2),
                    "gap_mm": round(gap, 2),
                    "a": {
                        key: first[key] for key in ("view", "index", "type", "text")
                    },
                    "b": {
                        key: second[key] for key in ("view", "index", "type", "text")
                    },
                    "positions_mm": [first["position_mm"], second["position_mm"]],
                }
            )

    off_frame = []
    for item in items:
        box = item["box"]
        sides = []
        if box[0] < frame[0]:
            sides.append("left")
        if box[1] < frame[1]:
            sides.append("bottom")
        if box[2] > frame[2]:
            sides.append("right")
        if box[3] > frame[3]:
            sides.append("top")
        if sides:
            off_frame.append(
                {
                    "view": item["view"],
                    "index": item["index"],
                    "type": item["type"],
                    "text": item["text"],
                    "sides": sides,
                    "position_mm": item["position_mm"],
                }
            )

    return {
        "frame_mm": {
            "min": [round(frame[0], 2), round(frame[1], 2)],
            "max": [round(frame[2], 2), round(frame[3], 2)],
        },
        "title_block_region_mm": (
            [round(value, 2) for value in title_block_region_mm]
            if title_block_region_mm
            else None
        ),
        "items": [
            {
                **{
                    key: item[key]
                    for key in ("view", "index", "type", "text", "position_mm", "size_mm")
                },
                "estimated_box_mm": [round(value, 3) for value in item["box"]],
            }
            for item in items
        ],
        "collisions": collisions,
        "duplicate_notes": duplicate_notes,
        "off_frame": off_frame,
        "counts": {
            "items": len(items),
            "collisions": len(collisions),
            "duplicate_note_groups": len(duplicate_notes),
            "off_frame": len(off_frame),
            "skipped": skipped,
        },
        "estimation": (
            "boxes are estimated from the measured annotation position and "
            "character count at {:.1f} mm text height; all returned text "
            "annotations, including sheet-format/title-block notes, are "
            "included. This screening estimate does not replace raster review."
            .format(text_height_mm)
        ),
    }


def layout_audit(
    sheet_name: str | None = None,
    min_gap_mm: float = 2.0,
    text_height_mm: float = 3.5,
    inset_mm: float | None = None,
    edge_band_mm: float = EDGE_BAND_MM,
) -> dict:
    """Audit the active drawing's annotation layout (plain result data)."""
    _, doc, _ = session.active_doc(("drawing",))
    listed = drawings.list_annotations(None, sheet_name)
    sheet_properties = drawings._sheet_properties(drawings._current_sheet(doc))
    size = sheet_properties.get("size_mm") or [420.0, 297.0]
    if inset_mm is None:
        paper = drawings.PAPER_SIZE_NAMES.get(sheet_properties.get("paper_code"))
        if paper in {"A0", "A1", "A2", "A3", "A4"}:
            # ISO 5457 filing margin on the left; other sides use the measured
            # 10 mm frame margin for the stock ISO templates.
            inset = {"left": 20.0, "bottom": 10.0, "right": 10.0, "top": 10.0}
        else:
            inset = FRAME_INSET_MM
    else:
        inset = float(inset_mm)
    result = audit_annotations(
        listed.get("views", []),
        size,
        inset_mm=inset,
        min_gap_mm=float(min_gap_mm),
        text_height_mm=float(text_height_mm),
        edge_band_mm=float(edge_band_mm),
        title_block_region_mm=None,
    )
    revision_table = _revision_table_bounds(doc)
    result["revision_table"] = revision_table
    if revision_table.get("present") and revision_table.get("box_mm"):
        box = revision_table["box_mm"]
        frame = result["frame_mm"]
        table_sides = []
        if box[0] < frame["min"][0]:
            table_sides.append("left")
        if box[1] < frame["min"][1]:
            table_sides.append("bottom")
        if box[2] > frame["max"][0]:
            table_sides.append("right")
        if box[3] > frame["max"][1]:
            table_sides.append("top")
        result["revision_table"]["off_frame_sides"] = table_sides
        result["revision_table"]["inside_frame"] = not table_sides
        result["revision_table_collisions"] = [
            {
                "view": item["view"],
                "index": item["index"],
                "type": item["type"],
                "overlap_area_mm2": round(
                    rect_overlap_area(tuple(item["estimated_box_mm"]), tuple(box)), 2
                ),
            }
            for item in result["items"]
            if rect_overlap_area(tuple(item["estimated_box_mm"]), tuple(box)) > 0.0
        ]
    else:
        result["revision_table_collisions"] = []
    result["audit_scope"] = {
        "text_annotations": "all sheet-view annotations, including title-block and frame notes",
        "revision_table": "exact table extent when the SOLIDWORKS API exposes it",
        "frame": "usable frame estimated from measured paper size and ISO insets",
        "leaders_and_frame_geometry": "require rendered raster review",
        "rendered_text_overflow": "estimated boxes require rendered raster review",
    }
    result["sheet"] = sheet_name or drawings._sheet_name(drawings._current_sheet(doc))
    return result


def _revision_table_bounds(doc) -> dict:
    """Return exact table bounds from its annotation position and cell sizes."""
    try:
        annotation = drawings._table_annotation(doc)
        if annotation is None:
            return {"present": False}
        table = binding.wrap(annotation.GetSpecificAnnotation(), "ITableAnnotation")
        columns = int(binding.value(table.ColumnCount))
        rows = int(binding.value(table.RowCount))
        width = sum(
            float(binding.value(table.GetColumnWidth(index)))
            for index in range(columns)
        )
        height = sum(
            float(binding.value(table.GetRowHeight(index)))
            for index in range(rows)
        )
        position = [float(value) for value in binding.value(annotation.GetPosition())]
        x, y = units.m_to_mm(position[0]), units.m_to_mm(position[1])
        width_mm, height_mm = units.m_to_mm(width), units.m_to_mm(height)
        return {
            "present": True,
            "rows": rows,
            "columns": columns,
            "box_mm": [x, y, x + width_mm, y + height_mm],
            "measurement": "annotation position plus exact row/column sizes",
        }
    except Exception as exc:
        return {
            "present": None,
            "status": f"bounds_unavailable: {type(exc).__name__}: {exc}",
        }
