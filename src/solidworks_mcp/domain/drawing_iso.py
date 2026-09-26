"""ISO drawing profile rules and pure manifest validation.

The COM layer reports drawing state; this module decides whether that state is
good enough for the project's ISO metric drawing contract. Keeping the rules
pure makes the release gate testable without a running SOLIDWORKS session.
"""
from __future__ import annotations

import math
from typing import Any


ISO_PROFILE_NAME = "iso_metric"
ISO_TYPELIB_MAJOR = 34
ISO_STANDARDS = (
    "ISO 128",
    "ISO 129-1",
    "ISO 5455",
    "ISO 5457",
    "ISO 7200",
    "ISO 1101",
)
ISO_PAPER_SIZES = frozenset({"A4", "A4_portrait", "A3", "A2", "A1", "A0"})
ISO_TEMPLATE_CODES = {
    "A4": 6,
    "A4_portrait": 7,
    "A3": 8,
    "A2": 9,
    "A1": 10,
    "A0": 11,
}
DEFAULT_REQUIRED_PROPERTIES = ("Title", "DrawingNumber", "Revision")
DEFAULT_MINIMUM_MODEL_VIEWS = 3


def profile_info() -> dict[str, Any]:
    """Return the public ISO profile contract."""
    return {
        "name": ISO_PROFILE_NAME,
        "units": "mm",
        "projection": "first_angle",
        "minimum_model_views": DEFAULT_MINIMUM_MODEL_VIEWS,
        "paper_sizes": sorted(ISO_PAPER_SIZES),
        "standards": list(ISO_STANDARDS),
        "default_required_properties": list(DEFAULT_REQUIRED_PROPERTIES),
        "limitations": [
            "stock ISO sheet frames are available; custom sheet artwork is not "
            "verified on the target SOLIDWORKS build",
            "model-item annotation import is not reliable on SW2026 SP0.0",
            "auto-dimensions require design-intent review before release",
        ],
    }


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if details:
        result["details"] = details
    return result


def _model_views(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        view
        for view in manifest.get("views", [])
        if view.get("type") != "sheet"
    ]


def _annotation_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    annotation_data = manifest.get("annotations") or {}
    for view in annotation_data.get("views", []):
        for annotation in view.get("annotations", []):
            kind = str(annotation.get("type", "other"))
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _readable_dimension_count(manifest: dict[str, Any]) -> int:
    """Count dimensions that carry an observable value or text.

    Measured on SW2026 SP0.0: DimXpert display dimensions return an empty
    ``IDisplayDimension.GetText`` while ``IDimension.Value`` holds the
    measured value in document units, so a numeric value is accepted as
    readable too.
    """
    count = 0
    annotation_data = manifest.get("annotations") or {}
    for view in annotation_data.get("views", []):
        for annotation in view.get("annotations", []):
            if annotation.get("type") != "dimension":
                continue
            if annotation.get("visible", True) is False:
                continue
            if annotation.get("show_dimension_value", True) is False:
                continue
            if str(annotation.get("text", "")).strip():
                count += 1
                continue
            try:
                value = float(annotation.get("value"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                count += 1
    return count


def _view_geometry_complete(view: dict[str, Any]) -> bool:
    outline = view.get("outline_mm") or {}
    minimum = outline.get("min")
    maximum = outline.get("max")
    position = view.get("position_mm")
    if not all(
        isinstance(value, (list, tuple)) and len(value) >= 2
        for value in (minimum, maximum, position)
    ):
        return False
    try:
        coordinates = [
            float(component)
            for value in (minimum, maximum, position)
            for component in value[:2]
        ]
        if not all(math.isfinite(value) for value in coordinates):
            return False
        min_x, min_y, max_x, max_y = coordinates[:4]
        return min_x < max_x and min_y < max_y
    except (TypeError, ValueError):
        return False


def _standard_view_role(view: dict[str, Any]) -> str | None:
    role = view.get("orientation")
    if role in {"front", "top", "right"}:
        return role
    raw = str(view.get("orientation_name", "")).strip().lower().lstrip("*")
    for candidate in ("front", "top", "right"):
        if raw == candidate or raw.endswith(candidate):
            return candidate
    return None


def _layout_issue(
    views: list[dict[str, Any]], projection: str | None
) -> dict[str, Any] | None:
    standard = {
        role: view
        for view in views
        if (role := _standard_view_role(view)) is not None
    }
    if not {"front", "top", "right"} <= set(standard):
        return _issue(
            "view_layout_unverified",
            "front, top and right view roles could not be identified",
            identified=sorted(standard),
        )
    try:
        front_x, front_y = (
            float(value) for value in standard["front"]["position_mm"][:2]
        )
        top_x, top_y = (
            float(value) for value in standard["top"]["position_mm"][:2]
        )
        right_x, right_y = (
            float(value) for value in standard["right"]["position_mm"][:2]
        )
    except (KeyError, TypeError, ValueError):
        return _issue(
            "view_layout_unverified",
            "front, top and right view positions could not be read back",
        )
    if projection == "first_angle":
        correct = top_y < front_y and right_x < front_x
    elif projection == "third_angle":
        correct = top_y > front_y and right_x > front_x
    else:
        return None
    if correct:
        return None
    return _issue(
        "projection_view_layout",
        "standard-view placement does not match the requested projection",
        projection=projection,
        positions={
            "front": [front_x, front_y],
            "top": [top_x, top_y],
            "right": [right_x, right_y],
        },
    )


def _overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_outline = first.get("outline_mm") or {}
    second_outline = second.get("outline_mm") or {}
    first_min = first_outline.get("min")
    first_max = first_outline.get("max")
    second_min = second_outline.get("min")
    second_max = second_outline.get("max")
    if not all(
        isinstance(value, (list, tuple)) and len(value) >= 2
        for value in (first_min, first_max, second_min, second_max)
    ):
        return False
    try:
        return (
            float(first_min[0]) < float(second_max[0])
            and float(second_min[0]) < float(first_max[0])
            and float(first_min[1]) < float(second_max[1])
            and float(second_min[1]) < float(first_max[1])
        )
    except (TypeError, ValueError):
        return False


def _views_outside_sheet(
    views: list[dict[str, Any]],
    sheet_size_mm: list[float],
    margin_mm: float,
) -> list[dict[str, Any]]:
    if len(sheet_size_mm) < 2:
        return []
    try:
        width, height = float(sheet_size_mm[0]), float(sheet_size_mm[1])
    except (TypeError, ValueError):
        return []
    outside = []
    for view in views:
        outline = view.get("outline_mm") or {}
        minimum = outline.get("min")
        maximum = outline.get("max")
        if not minimum or not maximum or len(minimum) < 2 or len(maximum) < 2:
            continue
        try:
            outside_usable_area = (
                float(minimum[0]) < margin_mm
                or float(minimum[1]) < margin_mm
                or float(maximum[0]) > width - margin_mm
                or float(maximum[1]) > height - margin_mm
            )
        except (TypeError, ValueError):
            outside_usable_area = True
        if outside_usable_area:
            outside.append(
                {
                    "view": view.get("name"),
                    "outline_mm": outline,
                    "sheet_size_mm": [width, height],
                }
            )
    return outside


def _positive_scale(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    try:
        return all(
            math.isfinite(float(component)) and float(component) > 0
            for component in value
        )
    except (TypeError, ValueError):
        return False


def _sheet_size(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        width, height = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(width) or not math.isfinite(height):
        return None
    if width <= 0 or height <= 0:
        return None
    return [width, height]


def validate_iso_manifest(
    manifest: dict[str, Any],
    *,
    minimum_model_views: int = DEFAULT_MINIMUM_MODEL_VIEWS,
    required_properties: list[str] | tuple[str, ...] | None = None,
    require_dimensions: bool = True,
    projection: str | None = "first_angle",
    allow_view_overlap: bool = False,
    frame_margin_mm: float = 10.0,
    require_title_block_display: bool = True,
) -> dict[str, Any]:
    """Validate a drawing manifest against the ISO metric release contract.

    This intentionally validates observable state rather than claiming that a
    stock frame or a generated note proves full standards compliance. The
    caller can relax release checks for an early preflight by setting
    ``require_dimensions=False`` and passing no required properties.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}

    document = manifest.get("document") or {}
    document_ok = document.get("type") == "drawing"
    checks["drawing_document"] = document_ok
    if not document_ok:
        errors.append(
            _issue(
                "wrong_document_type",
                "the active document is not a drawing",
                document_type=document.get("type"),
            )
        )

    sheet = manifest.get("sheet") or {}
    paper_size = sheet.get("paper_size")
    paper_ok = paper_size in ISO_PAPER_SIZES
    checks["iso_paper_size"] = paper_ok
    if not paper_ok:
        errors.append(
            _issue(
                "non_iso_paper",
                "the active sheet is not an ISO A4-A0 paper size",
                paper_size=paper_size,
                allowed=sorted(ISO_PAPER_SIZES),
            )
        )

    units = manifest.get("units") or {}
    units_ok = units.get("metric") is True or units.get("length_unit") == 0
    checks["metric_units"] = units_ok
    if not units_ok:
        errors.append(
            _issue(
                "non_metric_units",
                "the drawing document length unit is not millimetres",
                units=units,
            )
        )

    frame_ok = bool(sheet.get("format"))
    checks["sheet_frame"] = frame_ok
    if not frame_ok:
        errors.append(
            _issue("missing_sheet_frame", "the active sheet has no sheet format")
        )
    template_ok = (
        paper_size in ISO_TEMPLATE_CODES
        and sheet.get("template_code") == ISO_TEMPLATE_CODES[paper_size]
    )
    checks["stock_iso_frame"] = template_ok
    if not template_ok:
        errors.append(
            _issue(
                "non_iso_sheet_frame",
                "the active sheet format is not the measured stock ISO frame",
                paper_size=paper_size,
                template_code=sheet.get("template_code"),
                expected_template_code=ISO_TEMPLATE_CODES.get(paper_size),
            )
        )

    scale = sheet.get("scale")
    scale_ok = _positive_scale(scale)
    checks["sheet_scale"] = scale_ok
    if not scale_ok:
        errors.append(_issue("invalid_sheet_scale", "the active sheet has no valid scale"))

    if projection is not None:
        expected_first_angle = projection == "first_angle"
        projection_ok = sheet.get("first_angle") == expected_first_angle
        checks["projection"] = projection_ok
        if not projection_ok:
            errors.append(
                _issue(
                    "projection_mismatch",
                    "the sheet projection does not match the ISO profile",
                    expected=projection,
                    measured=("first_angle" if sheet.get("first_angle") else "third_angle"),
                )
            )

    model_views = _model_views(manifest)
    views_ok = len(model_views) >= max(1, int(minimum_model_views))
    checks["minimum_model_views"] = views_ok
    if not views_ok:
        errors.append(
            _issue(
                "too_few_model_views",
                "the drawing does not contain the required number of model views",
                required=max(1, int(minimum_model_views)),
                measured=len(model_views),
            )
        )

    geometry_missing = [
        view.get("name") for view in model_views if not _view_geometry_complete(view)
    ]
    geometry_ok = not geometry_missing
    checks["view_geometry"] = geometry_ok
    if not geometry_ok:
        errors.append(
            _issue(
                "unreadable_view_geometry",
                "one or more model views have no complete position and outline",
                views=geometry_missing,
            )
        )

    layout_issue = _layout_issue(model_views, projection)
    layout_required = int(minimum_model_views) >= DEFAULT_MINIMUM_MODEL_VIEWS
    layout_ok = layout_issue is None or not layout_required
    checks["projection_view_layout"] = layout_ok
    if layout_issue is not None and layout_required:
        errors.append(layout_issue)

    rebuild = manifest.get("rebuild") or {}
    rebuild_ok = bool(rebuild.get("ok")) and not (rebuild.get("whats_wrong") or {}).get(
        "count", 0
    )
    checks["rebuild"] = rebuild_ok
    if not rebuild_ok:
        errors.append(
            _issue(
                "rebuild_errors",
                "the drawing does not rebuild cleanly",
                rebuild=rebuild,
            )
        )

    annotation_counts = _annotation_counts(manifest)
    if require_dimensions:
        readable_dimensions = _readable_dimension_count(manifest)
        dimensions_ok = readable_dimensions > 0
        checks["dimensions"] = dimensions_ok
        if not dimensions_ok:
            errors.append(
                _issue(
                    "missing_dimensions",
                    "the drawing has no visible dimensions with readable text",
                    dimension_annotations=annotation_counts.get("dimension", 0),
                    readable_dimensions=readable_dimensions,
                )
            )
    else:
        checks["dimensions"] = True

    properties = {
        str(name): str(value)
        for name, value in (manifest.get("properties") or {}).items()
    }
    property_names = tuple(
        required_properties
        if required_properties is not None
        else DEFAULT_REQUIRED_PROPERTIES
    )
    missing_properties = [
        name for name in property_names if not str(properties.get(name, "")).strip()
    ]
    properties_ok = not missing_properties
    checks["required_properties"] = properties_ok
    if not properties_ok:
        errors.append(
            _issue(
                "missing_properties",
                "required ISO title-block properties are missing",
                missing=missing_properties,
            )
        )

    title_block = sheet.get("title_block") or {}
    matched_properties = title_block.get("matched_properties") or {}
    title_block_ok = not property_names or all(
        matched_properties.get(name) is True for name in property_names
    )
    checks["title_block_display"] = title_block_ok or not require_title_block_display
    if require_title_block_display and not title_block_ok:
        errors.append(
            _issue(
                "title_block_display_unverified",
                "required title-block property display was not read back",
                required= list(property_names),
                title_block=title_block,
            )
        )

    sheet_size = _sheet_size(sheet.get("size_mm"))
    size_ok = sheet_size is not None
    checks["sheet_size"] = size_ok
    if not size_ok:
        errors.append(_issue("invalid_sheet_size", "the active sheet has no valid size"))
    outside = _views_outside_sheet(model_views, sheet_size or [], frame_margin_mm)
    layout_ok = size_ok and not outside
    checks["view_bounds"] = layout_ok
    if not layout_ok:
        errors.append(
            _issue(
                "view_outside_usable_sheet",
                "one or more model views cross the sheet usable-area margin",
                views=outside,
                margin_mm=frame_margin_mm,
            )
        )

    overlaps = []
    if not allow_view_overlap:
        for index, first in enumerate(model_views):
            for second in model_views[index + 1 :]:
                if _overlap(first, second):
                    overlaps.append([first.get("name"), second.get("name")])
    overlap_ok = not overlaps
    checks["view_overlap"] = overlap_ok
    if not overlap_ok:
        errors.append(
            _issue(
                "view_overlap",
                "model view outlines overlap",
                pairs=overlaps,
            )
        )

    if not manifest.get("limitations_acknowledged"):
        warnings.append(
            _issue(
                "standards_scope",
                "this validator checks observable drawing state; visual ISO review "
                "and company drafting rules still require human approval",
            )
        )

    return {
        "valid": not errors,
        "profile": profile_info(),
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "annotation_counts": annotation_counts,
        "readable_dimensions": _readable_dimension_count(manifest),
        "required_properties": list(property_names),
        "model_view_count": len(model_views),
    }
