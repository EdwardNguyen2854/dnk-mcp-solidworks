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
EDGE_BAND_MM = 12.0
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
    inset_mm: float = FRAME_INSET_MM,
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
    frame = (
        (inset_mm, inset_mm, width_mm - inset_mm, height_mm - inset_mm)
    )
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
                }
            )

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
                key: item[key]
                for key in ("view", "index", "type", "text", "position_mm", "size_mm")
            }
            for item in items
        ],
        "collisions": collisions,
        "off_frame": off_frame,
        "counts": {
            "items": len(items),
            "collisions": len(collisions),
            "off_frame": len(off_frame),
            "skipped": skipped,
        },
        "estimation": (
            "boxes are estimated from the measured annotation position and "
            "character count at {:.1f} mm text height; they are a screening "
            "aid, not measured text bounds. The {:.0f} mm border band and the "
            "title-block region are skipped as sheet-format content".format(
                text_height_mm, edge_band_mm
            )
        ),
    }


def layout_audit(
    sheet_name: str | None = None,
    min_gap_mm: float = 2.0,
    text_height_mm: float = 3.5,
    inset_mm: float = FRAME_INSET_MM,
    edge_band_mm: float = EDGE_BAND_MM,
) -> dict:
    """Audit the active drawing's annotation layout (plain result data)."""
    _, doc, _ = session.active_doc(("drawing",))
    listed = drawings.list_annotations(None, sheet_name)
    size = drawings._sheet_properties(drawings._current_sheet(doc)).get(
        "size_mm"
    ) or [420.0, 297.0]
    result = audit_annotations(
        listed.get("views", []),
        size,
        inset_mm=float(inset_mm),
        min_gap_mm=float(min_gap_mm),
        text_height_mm=float(text_height_mm),
        edge_band_mm=float(edge_band_mm),
        title_block_region_mm=title_block_region(listed),
    )
    result["sheet"] = sheet_name or drawings._sheet_name(drawings._current_sheet(doc))
    return result
