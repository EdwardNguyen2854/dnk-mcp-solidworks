"""Engineering drawings: sheets, model views and annotations."""
from __future__ import annotations

import math
import re
from pathlib import Path

from ..com import binding, units
from ..config import get_config
from ..errors import (
    ComCallError,
    InvalidParameterError,
    PathNotFoundError,
    SelectionError,
    VerificationError,
    WrongDocumentTypeError,
)
from . import drawing_iso, inspect, session, sketch

STANDARD_VIEWS = {
    "front": "*Front",
    "back": "*Back",
    "left": "*Left",
    "right": "*Right",
    "top": "*Top",
    "bottom": "*Bottom",
    "isometric": "*Isometric",
    "trimetric": "*Trimetric",
    "dimetric": "*Dimetric",
}

# swInsertAnnotation_e bit masks. "dimensions" is deliberately all three
# dimension flags: the bare swInsertDimensions bit alone imports nothing.
ANNOTATION_TYPES = {
    "dimensions": 8 | 32768 | 524288,
    "marked_for_drawing": 32768,
    "not_marked_for_drawing": 524288,
    "hole_callouts": 1048576,
    "hole_wizard_profile": 65536,
    "hole_wizard_location": 131072,
    "notes": 64,
    "datums": 2,
    "geometric_tolerances": 32,
    "surface_finish": 128,
    "cosmetic_threads": 1,
    "axes": 512,
}
DEFAULT_ANNOTATION_TYPES = ("dimensions",)
ANNOTATION_SOURCES = {
    "entire_model": 0,
    "selected_feature": 1,
    "selected_component": 2,
    "assembly_only": 3,
}
ANNOTATION_TYPE_NAMES = {
    1: "cosmetic_thread",
    2: "datum_tag",
    3: "datum_target",
    4: "dimension",
    5: "geometric_tolerance",
    6: "note",
    7: "surface_finish",
    8: "weld_symbol",
    9: "custom_symbol",
    13: "center_mark",
    14: "table",
    15: "centerline",
    18: "revision_cloud",
}
ANNOTATION_RESULT_TYPES = {
    "dimensions": {"dimension"},
    "marked_for_drawing": {"dimension"},
    "not_marked_for_drawing": {"dimension"},
    "notes": {"note"},
    "datums": {"datum_tag", "datum_target"},
    "geometric_tolerances": {"geometric_tolerance"},
    "surface_finish": {"surface_finish"},
    "cosmetic_threads": {"cosmetic_thread"},
    "axes": {"centerline"},
}
AUTODIM_SCHEMES = {"baseline": 1, "ordinate": 2, "chain": 3, "centerline": 4}
AUTODIM_HORIZONTAL = {"below": -1, "above": 1}
AUTODIM_VERTICAL = {"left": -1, "right": 1}
AUTODIM_ENTITIES = {"all": 1, "selected": 2}

# swDrawingViewTypes_e, measured off swconst.tlb (34.0).
VIEW_TYPES = {
    1: "sheet",
    2: "section",
    3: "detail",
    4: "projected",
    5: "auxiliary",
    6: "standard",
    7: "named",
    8: "relative",
    9: "detached",
    10: "alternate_position",
}

# swDwgPaperSizes_e, measured off swconst.tlb (34.0). swDwgTemplates_e uses
# the same code per size (plus 12 custom, 13 none), which is why SetupSheet5
# takes the paper code as both PaperSize and TemplateIn to load the stock
# frame (see COM-QUIRKS).
PAPER_SIZES = {
    "A": 0,
    "A_portrait": 1,
    "B": 2,
    "C": 3,
    "D": 4,
    "E": 5,
    "A4": 6,
    "A4_portrait": 7,
    "A3": 8,
    "A2": 9,
    "A1": 10,
    "A0": 11,
    "custom": 12,
}
PAPER_SIZE_NAMES = {value: name for name, value in PAPER_SIZES.items()}
PAPER_SIZE_MM = {
    "A": (279.4, 215.9),
    "A_portrait": (215.9, 279.4),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
    "A4": (297.0, 210.0),
    "A4_portrait": (210.0, 297.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}
DEFAULT_PAPER_SIZE = "A3"

# Arrangement defaults: 3.5 mm drawing text plus arrows needs roughly 9 mm of
# clear corridor, measured against DimXpert output on SW2026 SP0.0. The frame
# margin keeps rows off the sheet border (stock ISO/ANSI frames sit ~10 mm in).
DIMENSION_SPACING_MM = 9.0
DIMENSION_MARGIN_MM = 8.0
DIMENSION_MIN_SPACING_MM = 6.5
FRAME_MARGIN_MM = 10.0

# swViewDisplayMode_e, measured off swconst.tlb (34.0).
DISPLAY_MODES = {
    "wireframe": 1,
    "hidden_lines_removed": 2,
    "hidden_lines_grayed": 3,
    "shaded": 4,
    "shaded_with_edges": 5,
}
DISPLAY_MODE_NAMES = {value: name for name, value in DISPLAY_MODES.items()}

# swDisplayTangentEdges_e, measured off swconst.tlb (34.0).
TANGENT_EDGES = {"hidden": 0, "visible_fonted": 1, "visible": 2}
TANGENT_EDGE_NAMES = {value: name for name, value in TANGENT_EDGES.items()}

# swTolType_e, measured off swconst.tlb (34.0).
TOLERANCE_TYPES = {
    "none": 0,
    "basic": 1,
    "bilateral": 2,
    "limits": 3,
    "symmetric": 4,
    "min": 5,
    "max": 6,
    "fit": 7,
    "fit_with_tolerance": 8,
    "fit_tolerance_only": 9,
}
TOLERANCE_TYPE_NAMES = {value: name for name, value in TOLERANCE_TYPES.items()}

# swGtolGeomCharSymbol_e, measured off swconst.tlb (34.0).
GTOL_SYMBOLS = {
    "symmetry": 13,
    "straightness": 14,
    "flatness": 15,
    "roundness": 16,
    "cylindricity": 17,
    "line_profile": 18,
    "surface_profile": 19,
    "angularity": 20,
    "perpendicularity": 21,
    "parallelism": 22,
    "position": 23,
    "concentricity": 24,
    "circular_runout": 25,
    "total_runout": 26,
    "circular_runout_open": 27,
    "total_runout_open": 28,
}
GTOL_SYMBOL_NAMES = {value: name for name, value in GTOL_SYMBOLS.items()}

# Material-condition modifiers stored in IGtol frame shorts. The glyphs are
# not exposed through the API; the read-back check proves the code, not the
# rendered symbol.
MATERIAL_CONDITIONS = {"none": 0, "mmc": 1, "lmc": 2}

# swSFSymType_e, measured off swconst.tlb (34.0).
SURFACE_FINISH_SYMBOLS = {
    "basic": 0,
    "machining_required": 1,
    "do_not_machine": 2,
}
SURFACE_FINISH_SYMBOL_NAMES = {
    value: name for name, value in SURFACE_FINISH_SYMBOLS.items()
}

# swBomType_e, measured off swconst.tlb (34.0).
BOM_TYPES = {
    "parts_only": 1,
    "top_level_only": 2,
    "indented": 3,
    "flattened": 4,
}

# swBalloonStyle_e / swBalloonFit_e / swBalloonLayoutType_e (34.0).
BALLOON_STYLES = {
    "none": 0,
    "circular": 1,
    "triangle": 2,
    "hexagon": 3,
    "box": 4,
    "diamond": 5,
    "pentagon": 6,
}
BALLOON_FITS = {
    "tightest": 0,
    "1_char": 1,
    "2_chars": 2,
    "3_chars": 3,
    "4_chars": 4,
    "5_chars": 5,
}
BALLOON_LAYOUTS = {
    "square": 1,
    "circle": 2,
    "top": 3,
    "bottom": 4,
    "right": 5,
    "left": 6,
}

# swDimensionType_e, measured off swconst.tlb (34.0). DimXpert returns
# swLinearDimension (2) for both axes of a linear dimension; IDimension.
# DimensionLineDirection is the reliable orientation signal.
DIMENSION_TYPES = {
    0: "unknown",
    1: "ordinate",
    2: "linear",
    3: "angular",
    4: "arc_length",
    5: "radial",
    6: "diameter",
    7: "horizontal_ordinate",
    8: "vertical_ordinate",
    9: "z_axis",
    10: "chamfer",
    11: "horizontal_linear",
    12: "vertical_linear",
    13: "scalar",
    14: "radial_linear",
    15: "diametric_linear",
    16: "angular_ordinate",
}

# swCenterMarkStyle_e, measured off swconst.tlb (34.0).
CENTER_MARK_STYLES = {
    "non_annotation": 1,
    "single": 2,
    "linear": 3,
    "circular": 4,
}

# swAutoInsertCenterMarkTypes_e: which entities get marks.
CENTER_MARK_TYPES = {"holes": 1, "fillets": 2, "slots": 4}

# swCreateSectionViewAtOptions_e, measured off the installed sldworks.tlb
# (worth checking: the published docs and the Slacker-LLC notes disagree).
SECTION_OPTIONS = {"not_aligned": 1, "exclude_fasteners": 64}

# swDetCircleShowType_e and swDetViewStyle_e, measured off swconst.tlb.
DETAIL_CIRCLE_STYLES = {"profile": 0, "circle": 1, "none": 2}
DETAIL_VIEW_STYLES = {"standard": 0, "broken": 1, "leader": 2, "no_leader": 3, "connected": 4}

# swViewEntityType_e: what GetVisibleEntities2 enumerates.
VIEW_ENTITY_EDGES = 1

# ICurve.Identity value for a circle (used to pick circular drawing edges).
CURVE_IDENTITY_CIRCLE = 3002

# IView.GetModelViewNames order on this build; index maps a standard name to
# the localized name the model reports.
MODEL_VIEW_ORDER = (
    "normal_to", "front", "back", "left", "right", "top", "bottom",
    "isometric", "trimetric", "dimetric",
)
SUPPORTED_DRAWING_TYPELIB_MAJOR = drawing_iso.ISO_TYPELIB_MAJOR


def _drawing(doc):
    try:
        major, _minor = binding.version()
    except Exception as exc:
        raise ComCallError(
            "could not determine the SOLIDWORKS drawing typelib version"
        ) from exc
    if major != SUPPORTED_DRAWING_TYPELIB_MAJOR:
        raise ComCallError(
            "drawing operations are not verified for this SOLIDWORKS typelib",
            typelib_major=major,
            supported_major=SUPPORTED_DRAWING_TYPELIB_MAJOR,
            hint="Use the supported SOLIDWORKS 2026 typelib or re-probe the "
            "drawing signatures before enabling this operation.",
        )
    return binding.wrap(doc, "IDrawingDoc")


def _extension(doc):
    """Return the typed model-document extension dispatch."""
    return binding.wrap(binding.value(doc.Extension), "IModelDocExtension")


def _unit_info(doc) -> dict:
    """Read the document length unit without relying on display text."""
    info: dict = {}
    try:
        length_unit = int(binding.value(doc.LengthUnit))
        info["length_unit"] = length_unit
        info["length_unit_name"] = "mm" if length_unit == 0 else str(length_unit)
        info["metric"] = length_unit == 0
    except Exception:
        info["metric"] = False
    try:
        raw = list(binding.value(doc.GetUnits()) or [])
        info["document_units"] = raw
        if raw:
            info["unit_system"] = int(raw[0])
    except Exception:
        pass
    return info


def _set_iso_units_on_doc(doc) -> dict:
    before = _unit_info(doc)
    if before.get("length_unit") != 0:
        # swUnitSystem_MMGS=5, swMM=0. Preserve the document's precision
        # settings where the typelib exposes them; the unit system is the only
        # value this ISO profile changes.
        raw = before.get("document_units") or []
        fract_base = int(raw[1]) if len(raw) > 1 else 0
        fract_denom = int(raw[2]) if len(raw) > 2 else 0
        sig_digits = int(raw[3]) if len(raw) > 3 else 2
        round_fraction = bool(raw[4]) if len(raw) > 4 else False
        doc.SetUnits(5, fract_base, fract_denom, sig_digits, round_fraction)
    after = _unit_info(doc)
    if after.get("length_unit") != 0:
        raise VerificationError(
            "SOLIDWORKS did not set the drawing document to millimetres",
            before=before,
            measured=after,
        )
    return {"before": before, "measured": after}


def set_iso_units() -> dict:
    """Set and verify the active drawing document's length unit to millimetres."""
    _, doc, _ = session.active_doc(("drawing",))
    _drawing(doc)
    units_data = _set_iso_units_on_doc(doc)
    return {
        "data": {"units": units_data["measured"]},
        "evidence": {"units": units_data},
    }


def create_drawing(
    model: str | None = None,
    template: str | None = None,
    paper_size: str = DEFAULT_PAPER_SIZE,
    scale: float = 1.0,
    first_angle: bool = True,
) -> dict:
    config = get_config()
    application = session.app()
    if model is None:
        raw_active = application.ActiveDoc
        if raw_active is None:
            raise SelectionError(
                "no model is available",
                hint="Open a part or assembly, or pass model explicitly.",
            )
        active = session.wrap_doc(raw_active)
        kind = session.DOC_TYPES.get(int(binding.value(active.GetType)), "unknown")
        if kind not in ("part", "assembly"):
            raise WrongDocumentTypeError(
                f"the active document is a {kind}; a drawing needs a part or "
                "assembly",
                hint="Activate the part/assembly or pass its path as model.",
            )
        model = str(binding.value(active.GetPathName) or binding.value(active.GetTitle))
    template_path = (
        Path(template).expanduser() if template else config.find_template("drawing")
    )
    if not template_path.exists():
        raise PathNotFoundError(f"drawing template not found: {template_path}")
    raw = application.NewDocument(str(template_path), 0, 0, 0)
    if raw is None:
        raw = application.ActiveDoc
    if raw is None:
        raise ComCallError("SOLIDWORKS did not create a drawing")
    doc = session.wrap_doc(raw)
    _drawing(doc)
    sheet_result = apply_sheet_format(paper_size, scale, first_angle)
    unit_evidence = _set_iso_units_on_doc(doc)
    sheet = sheet_result.get("data", sheet_result)
    return {
        "data": {
            "document": session.doc_info(doc),
            "model": model,
            "sheet": sheet,
            "units": unit_evidence["measured"],
        },
        "evidence": {
            "units": unit_evidence,
            "sheet": sheet_result.get("evidence", sheet_result),
        },
    }


def _resolved_view_name(application, model: str | None, view: str) -> str:
    """Map a standard orientation to the name this install actually uses.

    Standard view names are localized (*Isometric is *等轴测 on a Chinese
    install) and CreateDrawViewFromModelView3 silently returns nothing for a
    name it does not recognise. Ask the model for its own names instead of
    hard-coding English, falling back to the English token.
    """
    english = STANDARD_VIEWS[view]
    wanted = MODEL_VIEW_ORDER.index(view)
    for raw in application.GetDocuments() or []:
        try:
            doc = session.wrap_doc(raw)
            path = str(binding.value(doc.GetPathName) or "")
            title = str(binding.value(doc.GetTitle) or "")
        except Exception:
            continue
        if model and model not in (path, title):
            continue
        try:
            names = [str(name) for name in binding.value(doc.GetModelViewNames()) or []]
        except Exception:
            continue
        if len(names) > wanted:
            return names[wanted]
    return english


def insert_model_view(
    view: str,
    x_mm: float = 100.0,
    y_mm: float = 150.0,
    model: str | None = None,
) -> dict:
    if view.lower() not in STANDARD_VIEWS:
        raise SelectionError(
            f"unknown standard view {view!r}", available=sorted(STANDARD_VIEWS)
        )
    application = session.app()
    _, doc, _ = session.active_doc(("drawing",))
    drawing = _drawing(doc)
    models = []
    if model:
        models.append(model)
    else:
        models.append("")
    view_name = _resolved_view_name(application, model, view.lower())
    created = None
    for candidate in models:
        raw = drawing.CreateDrawViewFromModelView3(
            candidate, view_name, units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0
        )
        if raw is not None:
            created = raw
            break
    if created is None:
        raise ComCallError(
            f"could not create {view!r} view",
            hint="Pass the model path or title explicitly.",
        )
    return {
        "data": {"view": view, "created": True, "name": _view_name(created)},
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def _decimal_scale(pair) -> float | None:
    """Return model:paper as a decimal from an ISheet scale pair."""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    try:
        numerator, denominator = float(pair[0]), float(pair[1])
    except (TypeError, ValueError):
        return None
    if numerator <= 0 or denominator <= 0:
        return None
    return numerator / denominator


def _outline_m(view) -> list[float]:
    values = [float(value) for value in binding.value(view.GetOutline()) or []]
    if len(values) < 4:
        raise VerificationError(
            "a drawing view has no outline to lay out", view=_view_name(view)
        )
    return values[:4]


def _move_view_by(view, dx: float, dy: float) -> None:
    position = [float(value) for value in binding.value(view.Position) or []]
    while len(position) < 3:
        position.append(0.0)
    view.Position = binding.r8_array(
        [position[0] + dx, position[1] + dy, position[2]]
    )


def _outlines_overlap(
    first: list[float], second: list[float], tolerance_m: float = 1e-6
) -> bool:
    return (
        first[0] < second[2] - tolerance_m
        and second[0] < first[2] - tolerance_m
        and first[1] < second[3] - tolerance_m
        and second[1] < first[3] - tolerance_m
    )


def _layout_standard_views(views: dict, gap_mm: float) -> dict:
    """Place the top/right views around the front view with a clear gap.

    Measured on SW2026 SP0.0: ``CreateDrawViewFromModelView3`` auto-scales a
    new view and updates the sheet scale, so fixed centre distances can
    overlap. This pass measures each outline, keeps the front view where it
    landed and moves the top/right views so their outlines clear the front
    outline by ``gap_mm`` while staying aligned with it.
    """
    gap = units.mm_to_m(gap_mm)
    before = {
        role: _outline_m(view) for role, view in views.items()
    }
    front = before["front"]
    front_cx = (front[0] + front[2]) / 2.0
    front_cy = (front[1] + front[3]) / 2.0
    top = before["top"]
    right = before["right"]
    # First angle: the top view sits below the front view; the view seen from
    # the right is projected to the left. Third angle mirrors both signs.
    top_target_y = front[1] - gap - (top[3] - top[1]) / 2.0
    right_target_x = front[0] - gap - (right[2] - right[0]) / 2.0
    _move_view_by(
        views["top"],
        front_cx - (top[0] + top[2]) / 2.0,
        top_target_y - (top[1] + top[3]) / 2.0,
    )
    _move_view_by(
        views["right"],
        right_target_x - (right[0] + right[2]) / 2.0,
        front_cy - (right[1] + right[3]) / 2.0,
    )
    measured_outlines = {
        role: _outline_m(view) for role, view in views.items()
    }
    names = list(views)
    for index, first_role in enumerate(names):
        for second_role in names[index + 1 :]:
            if _outlines_overlap(
                measured_outlines[first_role], measured_outlines[second_role]
            ):
                raise VerificationError(
                    "standard views still overlap after layout",
                    views=[first_role, second_role],
                )
    layout = {}
    for role, outline in measured_outlines.items():
        layout[role] = {
            "name": _view_name(views[role]),
            "outline_mm": {
                "min": [round(units.m_to_mm(v), 2) for v in outline[0:2]],
                "max": [round(units.m_to_mm(v), 2) for v in outline[2:4]],
            },
        }
    layout["gaps_mm"] = {
        "top_below_front": round(
            units.m_to_mm(front[1] - measured_outlines["top"][3]), 2
        ),
        "right_left_of_front": round(
            units.m_to_mm(front[0] - measured_outlines["right"][2]), 2
        ),
    }
    return layout


def insert_standard_views(
    model: str | None = None,
    front_mm: list[float] | None = None,
    gap_mm: float = 20.0,
    projection: str = "first_angle",
    scale: float | None = None,
) -> dict:
    """Insert front/top/right views at one scale and lay them out without overlap.

    The sheet scale measured before insertion is applied to every view (and the
    sheet) so auto-scaling cannot leave mixed scales; pass ``scale`` to choose
    another scale explicitly.
    """
    if projection not in ("first_angle", "third_angle"):
        raise InvalidParameterError(
            "projection must be first_angle or third_angle",
            available=["first_angle", "third_angle"],
        )
    front = front_mm or (
        [240.0, 160.0] if projection == "first_angle" else [120.0, 160.0]
    )
    if not isinstance(front, (list, tuple)) or len(front) != 2:
        raise InvalidParameterError("front_mm must contain [x_mm, y_mm]")
    try:
        front = [float(front[0]), float(front[1])]
        gap_mm = float(gap_mm)
    except (TypeError, ValueError) as exc:
        raise InvalidParameterError("front_mm and gap_mm must be numeric") from exc
    if gap_mm <= 0:
        raise InvalidParameterError("gap_mm must be positive")
    _, doc, _ = session.active_doc(("drawing",))
    sheet_props = _sheet_properties(_current_sheet(doc))
    base_scale = _decimal_scale(sheet_props.get("scale")) or 1.0
    if scale is not None:
        try:
            base_scale = float(scale)
        except (TypeError, ValueError) as exc:
            raise InvalidParameterError("scale must be numeric") from exc
        if base_scale <= 0:
            raise InvalidParameterError("scale must be positive")
    placements = [
        ("front", front[0], front[1]),
        ("top", front[0], front[1] - gap_mm),
        ("right", front[0] - gap_mm, front[1]),
    ]
    created = {}
    for view, x, y in placements:
        result = insert_model_view(view, x, y, model)
        created[view] = result["data"]["name"]
    active_sheet = _sheet_name(_current_sheet(doc))
    views = {}
    for role, name in created.items():
        for view in _views(doc, active_sheet):
            if _view_name(view) == name:
                views[role] = view
                break
        if role not in views:
            raise VerificationError(
                "the inserted view disappeared before layout", view=name
            )
    for role, view in views.items():
        if abs(float(binding.value(view.ScaleDecimal)) - base_scale) > 1e-9:
            view.ScaleDecimal = base_scale
    numerator, denominator = _metric_scale(base_scale)
    sheet = _current_sheet(doc)
    sheet.SetScale(numerator, denominator, True, True)
    measured_sheet_scale = _decimal_scale(_sheet_properties(sheet).get("scale"))
    if (
        measured_sheet_scale is None
        or abs(measured_sheet_scale - base_scale) > 1e-6
    ):
        raise VerificationError(
            "SOLIDWORKS did not set the sheet scale",
            expected_scale=base_scale,
            measured=measured_sheet_scale,
        )
    layout = _layout_standard_views(views, gap_mm)
    mismatched = {}
    for role, view in views.items():
        try:
            measured_scale = float(binding.value(view.ScaleDecimal))
        except Exception:
            measured_scale = None
        if measured_scale is None or abs(measured_scale - base_scale) > 1e-6:
            mismatched[role] = {
                "name": _view_name(view),
                "measured_scale": measured_scale,
            }
    if mismatched:
        raise VerificationError(
            "views did not take the drawing scale",
            expected_scale=base_scale,
            views=mismatched,
        )
    return {
        "data": {
            "views": created,
            "model": model,
            "projection": projection,
            "front_mm": front,
            "gap_mm": gap_mm,
            "scale": base_scale,
            "layout": layout,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "views": list_drawing_views(active_sheet),
        },
    }


def _view_name(view) -> str:
    for member in ("Name", "GetName2", "GetName"):
        try:
            value = getattr(view, member)
            return str(binding.value(value))
        except Exception:
            continue
    return "<unnamed>"


def _flatten_views(items) -> list:
    if items is None:
        return []
    if not isinstance(items, (tuple, list)):
        return [items]
    flat: list = []
    for item in items:
        if isinstance(item, (tuple, list)):
            flat.extend(_flatten_views(item))
        else:
            flat.append(item)
    return flat


def _view_sheet_name(view) -> str | None:
    try:
        raw = binding.value(view.Sheet)
        if raw is None:
            return None
        return _sheet_name(binding.wrap(raw, "ISheet"))
    except Exception:
        return None


def _orientation_role(view) -> str | None:
    try:
        raw = str(binding.value(view.GetOrientationName) or "")
    except Exception:
        return None
    normalized = raw.strip().lower().lstrip("*")
    for role, token in STANDARD_VIEWS.items():
        expected = token.lower().lstrip("*")
        if normalized == expected or normalized.endswith(expected):
            return role
    return None


def _views(doc, sheet_name: str | None = None) -> list:
    drawing = _drawing(doc)
    views = []
    for raw in _flatten_views(drawing.GetViews()):
        try:
            view = binding.wrap(raw, "IView")
            if sheet_name is not None and _view_sheet_name(view) != sheet_name:
                continue
            views.append(view)
        except Exception:
            continue
    return views


def _view_info(view) -> dict:
    info = {"name": _view_name(view)}
    info["type"] = _view_type_name(view)
    sheet_name = _view_sheet_name(view)
    if sheet_name:
        info["sheet_name"] = sheet_name
    orientation = _orientation_role(view)
    if orientation:
        info["orientation"] = orientation
    try:
        orientation_name = str(binding.value(view.GetOrientationName) or "")
        if orientation_name:
            info["orientation_name"] = orientation_name
    except Exception:
        pass
    try:
        info["sheet"] = int(binding.value(view.Type)) == 1
    except Exception:
        pass
    position = _view_position_mm(view)
    if position is not None:
        info["position_mm"] = position
    try:
        info["scale"] = round(float(binding.value(view.ScaleDecimal)), 6)
    except Exception:
        pass
    try:
        info["display_mode"] = DISPLAY_MODE_NAMES.get(
            int(binding.value(view.GetDisplayMode2)), "unknown"
        )
    except Exception:
        pass
    try:
        info["tangent_edges"] = TANGENT_EDGE_NAMES.get(
            int(binding.value(view.GetDisplayTangentEdges2)), "unknown"
        )
    except Exception:
        pass
    try:
        referenced = str(binding.value(view.GetReferencedModelName) or "")
        if referenced:
            info["model"] = referenced
    except Exception:
        pass
    try:
        info["dimensions"] = int(view.GetDimensionCount())
    except Exception:
        pass
    try:
        outline = binding.value(view.GetOutline())
        if outline and len(outline) >= 4:
            info["outline_mm"] = {
                "min": [round(units.m_to_mm(v), 2) for v in outline[0:2]],
                "max": [round(units.m_to_mm(v), 2) for v in outline[2:4]],
            }
    except Exception:
        pass
    return info


def list_drawing_views(sheet_name: str | None = None) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    views = [_view_info(view) for view in _views(doc, sheet_name)]
    return {"views": views, "count": len(views), "sheet": sheet_name}


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------


def _sheet_name(sheet) -> str | None:
    if sheet is None:
        return None
    try:
        return str(sheet.GetName())
    except Exception:
        return None


def _sheet_names(doc) -> list[str]:
    return [str(name) for name in _drawing(doc).GetSheetNames() or []]


def _current_sheet(doc):
    raw = _drawing(doc).GetCurrentSheet()
    if raw is None:
        return None
    return binding.wrap(raw, "ISheet")


def _sheet_properties(sheet) -> dict:
    """Read scale, projection angle and size off ISheet.GetProperties2.

    Layout on this build: [paper size, template, scale1, scale2, first_angle,
    width, height] with the dimensions in metres.
    """
    try:
        values = list(sheet.GetProperties2() or [])
        if len(values) < 7:
            return {}
        details = {
            "paper_code": int(values[0]),
            "template_code": int(values[1]),
            "scale": [float(values[2]), float(values[3])],
            "first_angle": bool(values[4]),
            "size_mm": [
                round(units.m_to_mm(float(values[5])), 2),
                round(units.m_to_mm(float(values[6])), 2),
            ],
        }
        try:
            format_name = str(binding.value(sheet.GetSheetFormatName) or "")
        except Exception:
            format_name = ""
        if format_name:
            details["format"] = format_name
        try:
            template_name = str(binding.value(sheet.GetTemplateName) or "")
        except Exception:
            template_name = ""
        if template_name:
            details["template_name"] = template_name
        paper = PAPER_SIZE_NAMES.get(int(values[0]))
        if paper:
            details["paper_size"] = paper
        return details
    except Exception:
        return {}


_PROPERTY_LINK = re.compile(r'\$(PRP(?:OSITE)?|PRPSHEET)\s*:\s*"([^"]+)"')


def _referenced_property_map() -> dict[str, str]:
    """Custom properties of the open part/assembly documents.

    ``$PRPSHEET:"X"`` links resolve against the drawing's referenced model;
    with several models open the maps are merged (single-model drawings are
    the normal case).
    """
    result: dict[str, str] = {}
    try:
        application = session.app()
        documents = list(application.GetDocuments() or [])
    except Exception:
        return result
    for raw in documents:
        try:
            candidate = session.wrap_doc(raw)
            kind = session.DOC_TYPES.get(
                int(binding.value(candidate.GetType)), "unknown"
            )
            if kind not in ("part", "assembly"):
                continue
            manager = binding.wrap(
                candidate.Extension.CustomPropertyManager(""),
                "ICustomPropertyManager",
            )
            for name in _property_names(manager):
                try:
                    result[name] = str(binding.value(manager.Get(name)) or "")
                except Exception:
                    continue
            path = str(binding.value(candidate.GetPathName) or "")
            title = str(binding.value(candidate.GetTitle) or "")
            result.setdefault("SW-File Name", Path(path).stem if path else title)
        except Exception:
            continue
    return result


def _system_property_map(doc) -> dict[str, str]:
    path = str(binding.value(doc.GetPathName) or "")
    title = str(binding.value(doc.GetTitle) or "")
    return {"SW-File Name": Path(path).stem if path else title.split(" - ")[0]}


def _note_info(
    note,
    properties: dict[str, str] | None = None,
    model_properties: dict[str, str] | None = None,
    system_properties: dict[str, str] | None = None,
) -> dict:
    """Read a note's text, property link and balloon state.

    ``properties`` (drawing custom properties), ``model_properties`` (the
    referenced part/assembly) and ``system_properties`` (SW-File Name and
    friends) resolve ``$PRP`` / ``$PRPSHEET`` links. Measured on SW2026 SP0.0:
    the API returns the raw link token, not the displayed value, so the
    resolved text has to be computed here.
    """
    text = str(binding.value(note.GetText) or "")
    linked = str(binding.value(note.PropertyLinkedText) or "")
    prompt = str(binding.value(note.PromptText) or "")
    info: dict = {
        "text": text,
        "property_linked_text": linked,
        "prompt": prompt,
    }
    source = linked or text
    if "$PRP" in source and (
        properties is not None
        or model_properties is not None
        or system_properties is not None
    ):

        def resolve(match):
            code, name = match.group(1), match.group(2)
            mappings = (
                (model_properties or {},)
                if code == "PRPSHEET"
                else (properties or {}, system_properties or {})
            )
            for mapping in mappings:
                if name in mapping:
                    return mapping[name]
            return match.group(0)

        info["resolved_text"] = _PROPERTY_LINK.sub(resolve, source)
        info["property_links"] = [
            f"${code}:{name}" for code, name in _PROPERTY_LINK.findall(source)
        ]
    try:
        info["is_balloon"] = bool(binding.value(note.IsBomBalloon))
    except Exception:
        pass
    try:
        annotation = binding.wrap(note.GetAnnotation(), "IAnnotation")
        info["visible"] = bool(binding.value(annotation.Visible))
    except Exception:
        pass
    return info


def _dimension_value(display) -> float | None:
    """Read IDimension.Value (document units; mm on a metric drawing)."""
    try:
        dimension = binding.wrap(display.GetDimension2(0), "IDimension")
        return float(binding.value(dimension.Value))
    except Exception:
        return None


def _tolerance_info(display) -> dict | None:
    """Read IDimensionTolerance state for a display dimension."""
    try:
        dimension = binding.wrap(display.GetDimension2(0), "IDimension")
        tolerance = binding.wrap(
            binding.value(dimension.Tolerance), "IDimensionTolerance"
        )
        code = int(binding.value(tolerance.Type))
    except Exception:
        return None
    info: dict = {
        "type": TOLERANCE_TYPE_NAMES.get(code, f"type_{code}"),
        "type_code": code,
    }
    if code in (TOLERANCE_TYPES["none"], TOLERANCE_TYPES["basic"]):
        return info
    # IDimensionTolerance getters return metres (system units); the tool
    # surface is millimetres.
    try:
        info["min"] = round(units.m_to_mm(float(tolerance.GetMinValue())), 6)
    except Exception:
        pass
    try:
        info["max"] = round(units.m_to_mm(float(tolerance.GetMaxValue())), 6)
    except Exception:
        pass
    if code in (
        TOLERANCE_TYPES["fit"],
        TOLERANCE_TYPES["fit_with_tolerance"],
        TOLERANCE_TYPES["fit_tolerance_only"],
    ):
        try:
            info["hole_fit"] = str(tolerance.GetHoleFitValue() or "")
        except Exception:
            pass
        try:
            info["shaft_fit"] = str(tolerance.GetShaftFitValue() or "")
        except Exception:
            pass
    return info


def _title_block_info(
    sheet,
    properties: dict[str, str] | None = None,
    sheet_notes: list[dict] | None = None,
) -> dict:
    """Read title-block notes and verify linked property values when possible.

    The stock ISO frame on this build is a set of static notes on the sheet
    view: ``ISheet.TitleBlock`` returns None and nothing is property-linked,
    so ``verified`` can only pass on a frame that actually carries links.
    ``sheet_notes`` are note entries from ``list_annotations``.
    """
    info: dict = {"available": False, "verified": False, "notes": []}
    object_notes: list[dict] = []
    if sheet is not None:
        try:
            raw = binding.value(sheet.TitleBlock)
        except Exception as exc:
            raw = None
            info["error"] = str(exc)
        if raw is not None:
            try:
                title_block = binding.wrap(raw, "ITitleBlock")
                for raw_note in _flatten_views(binding.value(title_block.GetNotes)):
                    object_notes.append(
                        _note_info(binding.wrap(raw_note, "INote"))
                    )
                info["available"] = True
            except Exception as exc:
                info["error"] = str(exc)
    sheet_notes = sheet_notes or []
    linked_notes = [note for note in sheet_notes if note.get("property_linked_text")]
    if sheet_notes:
        info["available"] = True
        info["sheet_note_count"] = len(sheet_notes)
        info["linked_note_count"] = len(linked_notes)
    candidates = [*object_notes, *sheet_notes]
    values = {
        str(name): str(value).strip()
        for name, value in (properties or {}).items()
    }
    matched = {}
    for name, value in values.items():
        if not value:
            continue
        matched[name] = any(
            note.get("visible", True)
            and str(note.get("text", "")).strip() == value
            for note in candidates
        ) or any(
            name.lower() in str(note.get("property_linked_text", "")).lower()
            and str(note.get("text", "")).strip() == value
            for note in candidates
        )
    info["matched_properties"] = matched
    info["verified"] = bool(matched) and all(matched.values())
    info["notes"] = [*object_notes, *linked_notes]
    return info


def list_sheets(properties: dict[str, str] | None = None) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    names = _sheet_names(doc)
    sheet = _current_sheet(doc)
    active = _sheet_name(sheet)
    data = {
        "sheets": [{"name": name, "active": name == active} for name in names],
        "count": len(names),
        "active_sheet": active,
    }
    data.update(_sheet_properties(sheet))
    data["title_block"] = _title_block_info(sheet, properties)
    return data


def _drawing_property_manager(doc):
    """Return the drawing document's custom-property manager."""
    _drawing(doc)
    raw = _extension(doc).CustomPropertyManager("")
    if raw is None:
        raise ComCallError("SOLIDWORKS did not provide a drawing property manager")
    return binding.wrap(raw, "ICustomPropertyManager")


def _property_names(manager) -> list[str]:
    try:
        raw = binding.value(manager.GetNames)
    except Exception:
        raw = None
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(name) for name in raw if str(name)]


def list_properties() -> dict:
    """Read drawing custom properties used by title-block links."""
    _, doc, _ = session.active_doc(("drawing",))
    manager = _drawing_property_manager(doc)
    properties: dict[str, str] = {}
    for name in _property_names(manager):
        try:
            properties[name] = str(binding.value(manager.Get(name)) or "")
        except Exception:
            properties[name] = ""
    return {"properties": properties, "count": len(properties)}


def set_property(name: str, value: str) -> dict:
    """Set one text custom property and verify its read-back value."""
    if not str(name).strip():
        raise InvalidParameterError("property name must not be empty")
    _, doc, _ = session.active_doc(("drawing",))
    manager = _drawing_property_manager(doc)
    names = _property_names(manager)
    existing = next(
        (candidate for candidate in names if candidate.lower() == str(name).lower()),
        None,
    )
    stored_name = existing or str(name)
    if existing is not None:
        manager.Set2(existing, str(value))
        operation = "set"
    else:
        # swCustomInfoText=30; swCustomPropertyReplaceValue=2 on typelib 34.0.
        manager.Add3(stored_name, 30, str(value), 2)
        operation = "add"
    properties = list_properties()["properties"]
    measured = properties.get(stored_name, "")
    if measured != str(value):
        raise VerificationError(
            "SOLIDWORKS did not retain the drawing property",
            property=stored_name,
            expected=str(value),
            measured=measured,
        )
    return {
        "data": {
            "name": stored_name,
            "value": str(value),
            "operation": operation,
            "properties": properties,
        },
        "evidence": {"properties": properties},
    }


def drawing_manifest() -> dict:
    """Collect the observable state used by the ISO release validator."""
    _, doc, _ = session.active_doc(("drawing",))
    sheet_data = list_sheets()
    try:
        property_data = list_properties()
        properties = property_data["properties"]
        property_error = None
    except Exception as exc:
        properties = {}
        property_error = str(exc)
    active_sheet = sheet_data.get("active_sheet")
    current_sheet = _current_sheet(doc)
    annotations = list_annotations(sheet_name=active_sheet)
    note_entries = [
        item
        for view in annotations["views"]
        for item in view["annotations"]
        if item.get("type") == "note"
    ]
    sheet_data["title_block"] = _title_block_info(
        current_sheet, properties, note_entries
    )
    rebuild = inspect.rebuild(doc)
    manifest = {
        "profile": drawing_iso.ISO_PROFILE_NAME,
        "document": session.doc_info(doc),
        "sheets": sheet_data.get("sheets", []),
        "active_sheet": active_sheet,
        "scope": {"sheet": active_sheet, "verified": active_sheet is not None},
        "sheet": {
            key: value
            for key, value in sheet_data.items()
            if key not in ("sheets", "count", "active_sheet")
        },
        "views": list_drawing_views(active_sheet)["views"],
        "annotations": annotations,
        "properties": properties,
        "units": _unit_info(doc),
        "rebuild": rebuild,
        "limitations_acknowledged": False,
    }
    if property_error:
        manifest["property_error"] = property_error
    return manifest


def iso_preflight() -> dict:
    """Run an early ISO readiness check without release-only requirements."""
    manifest = drawing_manifest()
    validation = drawing_iso.validate_iso_manifest(
        manifest,
        minimum_model_views=1,
        required_properties=[],
        require_dimensions=False,
        projection="first_angle",
        allow_view_overlap=True,
        require_title_block_display=False,
    )
    return {"manifest": manifest, "preflight": validation}


def validate_iso_drawing(
    minimum_model_views: int = drawing_iso.DEFAULT_MINIMUM_MODEL_VIEWS,
    required_properties: list[str] | None = None,
    require_dimensions: bool = True,
    projection: str = "first_angle",
    allow_view_overlap: bool = False,
    limitations_acknowledged: bool = False,
    require_title_block_display: bool = False,
) -> dict:
    """Validate the active drawing against the ISO metric profile.

    The stock ISO frame on this build carries static title-block notes with no
    property links, so title-block *display* is advisory by default; enable it
    for a company frame that links the properties.
    """
    manifest = drawing_manifest()
    manifest["limitations_acknowledged"] = bool(limitations_acknowledged)
    validation = drawing_iso.validate_iso_manifest(
        manifest,
        minimum_model_views=minimum_model_views,
        required_properties=required_properties,
        require_dimensions=require_dimensions,
        projection=projection,
        allow_view_overlap=allow_view_overlap,
        require_title_block_display=require_title_block_display,
    )
    return {"manifest": manifest, "validation": validation}


def _metric_scale(scale: float) -> tuple[float, float]:
    """Return SetupSheet5 Scale1/Scale2 for a decimal model:paper scale."""
    if scale <= 0:
        raise InvalidParameterError("sheet scale must be positive")
    if scale >= 1.0:
        return float(scale), 1.0
    return 1.0, float(1.0 / scale)


def apply_sheet_format(
    paper_size: str = DEFAULT_PAPER_SIZE,
    scale: float = 1.0,
    first_angle: bool = True,
    sheet_name: str | None = None,
) -> dict:
    """Apply the stock standard frame (border and title block) to a sheet.

    Passing the paper code as SetupSheet5's TemplateIn loads this build's
    stock template: ISO frames for A4-A0, ANSI for A-E. The measured limits
    are in COM-QUIRKS: TemplateName (.slddrt) is ignored and
    ISldWorks.LoadFile4 refuses .slddrt, so GB/DIN/JIS artwork is not
    reachable from COM here.
    """
    _, doc, _ = session.active_doc(("drawing",))
    size_code = PAPER_SIZES.get(paper_size)
    if size_code is None:
        raise InvalidParameterError(
            f"unknown paper size {paper_size!r}", available=sorted(PAPER_SIZES)
        )
    if paper_size == "custom":
        raise InvalidParameterError(
            "custom paper has no standard frame; pick a named size"
        )
    if sheet_name is not None:
        names = _sheet_names(doc)
        if sheet_name not in names:
            raise SelectionError(f"sheet {sheet_name!r} not found", available=names)
        _drawing(doc).ActivateSheet(sheet_name)
    sheet = _current_sheet(doc)
    name = _sheet_name(sheet) or "Sheet1"
    numerator, denominator = _metric_scale(scale)
    _drawing(doc).SetupSheet5(
        name,
        size_code,
        size_code,
        numerator,
        denominator,
        bool(first_angle),
        "",
        0.0,
        0.0,
        "",
        False,
    )
    # Re-read through a fresh wrapper: SetupSheet5 can replace the sheet
    # object, and a stale wrapper reports the pre-call state.
    sheet = _current_sheet(doc)
    try:
        format_name = str(binding.value(sheet.GetSheetFormatName) or "")
    except Exception:
        format_name = ""
    props = _sheet_properties(sheet)
    if not format_name:
        raise VerificationError(
            "SOLIDWORKS did not apply a standard sheet frame",
            sheet=name,
            paper_size=paper_size,
            format=format_name,
            hint="The stock template for this paper size carries no sheet "
            "format, or SOLIDWORKS refused the setup call.",
        )
    expected = PAPER_SIZE_MM[paper_size]
    measured = props.get("size_mm", [0.0, 0.0])
    if (
        not isinstance(measured, (list, tuple))
        or len(measured) < 2
        or abs(float(measured[0]) - expected[0]) > 0.5
        or abs(float(measured[1]) - expected[1]) > 0.5
    ):
        raise VerificationError(
            "sheet size does not match the requested paper",
            expected_mm=list(expected),
            measured_mm=measured,
        )
    measured_scale = props.get("scale")
    if (
        not isinstance(measured_scale, (list, tuple))
        or len(measured_scale) != 2
        or any(
            abs(float(actual) - float(expected_scale)) > 1e-6
            for actual, expected_scale in zip(
                measured_scale, (numerator, denominator)
            )
        )
    ):
        raise VerificationError(
            "sheet scale does not match the requested scale",
            expected=[numerator, denominator],
            measured=measured_scale,
        )
    measured_first_angle = props.get("first_angle")
    if measured_first_angle is not None and bool(measured_first_angle) != bool(first_angle):
        raise VerificationError(
            "sheet projection does not match the requested projection",
            expected=bool(first_angle),
            measured=bool(measured_first_angle),
        )
    if props.get("template_code") != size_code:
        raise VerificationError(
            "SOLIDWORKS did not retain the requested stock sheet template",
            expected_template_code=size_code,
            measured_template_code=props.get("template_code"),
        )
    measured_data = {
        "sheet": name,
        "paper_size": props.get("paper_size", paper_size),
        "format": format_name,
        "template_code": props.get("template_code"),
        "scale": measured_scale,
        "first_angle": bool(
            measured_first_angle if measured_first_angle is not None else first_angle
        ),
        "size_mm": measured,
    }
    return {
        "data": measured_data,
        "evidence": {
            "requested": {
                "paper_size": paper_size,
                "scale": [numerator, denominator],
                "first_angle": bool(first_angle),
            },
            "measured": measured_data,
            "rebuild": inspect.rebuild(doc),
        },
    }


def add_sheet(
    name: str | None = None,
    paper_size: str = "A3",
    scale_numerator: float = 1,
    scale_denominator: float = 1,
    first_angle: bool = True,
) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    size_code = PAPER_SIZES.get(paper_size)
    if size_code is None:
        raise InvalidParameterError(
            f"unknown paper size {paper_size!r}", available=sorted(PAPER_SIZES)
        )
    if scale_numerator <= 0 or scale_denominator <= 0:
        raise InvalidParameterError("sheet scale must be positive")
    before = _sheet_names(doc)
    sheet_name = name or f"Sheet{len(before) + 1}"
    created = bool(
        _drawing(doc).NewSheet3(
            sheet_name,
            size_code,
            size_code,
            float(scale_numerator),
            float(scale_denominator),
            bool(first_angle),
            "",
            0.0,
            0.0,
            "",
        )
    )
    after = _sheet_names(doc)
    if sheet_name not in after:
        raise VerificationError(
            "SOLIDWORKS did not add the sheet",
            created=created,
            sheets=after,
        )
    frame = None
    frame_evidence = None
    if paper_size != "custom":
        frame_result = apply_sheet_format(
            paper_size,
            scale_numerator / scale_denominator,
            first_angle,
        )
        frame = frame_result.get("data", frame_result)
        frame_evidence = frame_result.get("evidence")
    return {
        "data": {
            "sheet": sheet_name,
            "created": created,
            "sheets": after,
            "frame": frame,
        },
        "evidence": {
            "frame": frame_evidence,
            "rebuild": inspect.rebuild(doc),
        },
    }


def activate_sheet(name: str) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    names = _sheet_names(doc)
    if name not in names:
        raise SelectionError(f"sheet {name!r} not found", available=names)
    activated = bool(_drawing(doc).ActivateSheet(name))
    active = _sheet_name(_current_sheet(doc))
    if activated and active != name:
        raise VerificationError(
            f"SOLIDWORKS did not activate sheet {name!r}", active_sheet=active
        )
    if not activated:
        raise ComCallError(f"SOLIDWORKS refused to activate sheet {name!r}")
    return {
        "data": {"activated": name, "active_sheet": active},
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


# ---------------------------------------------------------------------------
# View operations
# ---------------------------------------------------------------------------


def _view_type_name(view) -> str:
    try:
        return VIEW_TYPES.get(int(binding.value(view.Type)), "unknown")
    except Exception:
        return "unknown"


def _view_position_mm(view) -> list[float] | None:
    try:
        position = list(binding.value(view.Position) or [])
        if len(position) >= 2:
            return [round(units.m_to_mm(position[0]), 4), round(units.m_to_mm(position[1]), 4)]
    except Exception:
        pass
    return None


def _active_view_name(doc) -> str | None:
    try:
        raw = _drawing(doc).ActiveDrawingView
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return _view_name(raw)
    except Exception:
        return None


def activate_view(name: str | None = None) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    resolved = _view_name(_model_view(doc, name))
    if not _drawing(doc).ActivateView(resolved):
        raise ComCallError(f"SOLIDWORKS could not activate view {resolved!r}")
    return {
        "data": {"view": resolved, "active_view": _active_view_name(doc)},
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def set_view(
    name: str,
    x_mm: float | None = None,
    y_mm: float | None = None,
    scale: float | None = None,
    display_mode: str | None = None,
    tangent_edges: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, name)
    if (x_mm is None) != (y_mm is None):
        raise InvalidParameterError("pass both x_mm and y_mm, or neither")
    if display_mode is not None and display_mode not in DISPLAY_MODES:
        raise InvalidParameterError(
            f"unknown display mode {display_mode!r}", available=sorted(DISPLAY_MODES)
        )
    if tangent_edges is not None and tangent_edges not in TANGENT_EDGES:
        raise InvalidParameterError(
            f"unknown tangent edge mode {tangent_edges!r}",
            available=sorted(TANGENT_EDGES),
        )
    if all(value is None for value in (x_mm, y_mm, scale, display_mode, tangent_edges)):
        raise InvalidParameterError(
            "pass at least one of x_mm/y_mm, scale, display_mode or tangent_edges"
        )
    if x_mm is not None:
        view.Position = binding.r8_array(
            [units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0]
        )
    if scale is not None:
        if scale <= 0:
            raise InvalidParameterError("scale must be positive")
        view.ScaleDecimal = float(scale)
    if display_mode is not None:
        view.SetDisplayMode3(False, DISPLAY_MODES[display_mode], False, False)
    if tangent_edges is not None:
        view.SetDisplayTangentEdges2(TANGENT_EDGES[tangent_edges])
    measured = _view_info(view)
    if x_mm is not None:
        position = measured.get("position_mm")
        if (
            not position
            or abs(position[0] - float(x_mm)) > 0.1
            or abs(position[1] - float(y_mm)) > 0.1
        ):
            raise VerificationError(
                "SOLIDWORKS did not retain the requested drawing-view position",
                requested_mm=[x_mm, y_mm],
                measured=position,
            )
    if scale is not None and abs(measured.get("scale", 0.0) - float(scale)) > 1e-6:
        raise VerificationError(
            "SOLIDWORKS did not retain the requested drawing-view scale",
            requested=scale,
            measured=measured.get("scale"),
        )
    if display_mode is not None and measured.get("display_mode") not in (
        display_mode,
        None,
    ):
        raise VerificationError(
            "SOLIDWORKS did not retain the requested drawing-view display mode",
            requested=display_mode,
            measured=measured.get("display_mode"),
        )
    if tangent_edges is not None and measured.get("tangent_edges") not in (
        tangent_edges,
        None,
    ):
        raise VerificationError(
            "SOLIDWORKS did not retain the requested tangent-edge mode",
            requested=tangent_edges,
            measured=measured.get("tangent_edges"),
        )
    return {
        "data": {"view": measured},
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def _view_centre_mm(view) -> tuple[float, float]:
    """The view's centre in sheet millimetres.

    Sketch geometry drawn inside a drawing view lives in the sheet's
    coordinate system **with the origin at the view's centre**, not at the
    sheet's corner. Measured on SW2026 SP0.0: a section line drawn with sheet
    coordinates lands one view-offset away from the geometry; SOLIDWORKS still
    creates a view labelled `section`, but it is never cut (see
    `docs/COM-QUIRKS.md`).
    """
    try:
        position = [float(value) for value in binding.value(view.Position)]
    except Exception:
        return (0.0, 0.0)
    if len(position) < 2:
        return (0.0, 0.0)
    return (units.m_to_mm(position[0]), units.m_to_mm(position[1]))


def _to_view_sketch_mm(view, x_mm: float, y_mm: float) -> tuple[float, float]:
    """Convert a sheet point to the view sketch's local millimetres."""
    centre_x, centre_y = _view_centre_mm(view)
    return (x_mm - centre_x, y_mm - centre_y)


def _draw_in_view(doc, parent_name: str | None, draw):
    """Draw reference geometry inside a view and leave it selected.

    Sketch geometry in a drawing belongs to whichever view is active, so the
    activate/draw/select dance happens together; section and detail views then
    consume the selection.
    """
    view = _model_view(doc, parent_name)
    resolved = _view_name(view)
    if not _drawing(doc).ActivateView(resolved):
        raise ComCallError(f"SOLIDWORKS could not activate view {resolved!r}")
    session.clear_selection(doc)
    manager = sketch._sketch_manager(doc)
    entity = draw(manager)
    if entity is None:
        # Some builds need the view sketch opened explicitly before geometry
        # lands; the Slacker-LLC source relies on ActivateView alone, so try
        # both and keep whichever works.
        manager.InsertSketch(True)
        entity = draw(manager)
    if entity is None:
        raise ComCallError(
            f"SOLIDWORKS did not draw the reference geometry in view {resolved!r}"
        )
    if not inspect.select_entity(entity, False, 0):
        raise SelectionError(
            "could not select the reference geometry just drawn",
            view=resolved,
        )
    return resolved, entity


def insert_projected_view(
    parent_view: str | None = None,
    direction: str = "right",
    offset_mm: float = 80.0,
    x_mm: float | None = None,
    y_mm: float | None = None,
    not_aligned: bool = False,
) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    parent = _model_view(doc, parent_view)
    parent_name = _view_name(parent)
    if (x_mm is None) != (y_mm is None):
        raise InvalidParameterError("pass both x_mm and y_mm, or neither")
    if x_mm is not None and y_mm is not None:
        position = (units.mm_to_m(x_mm), units.mm_to_m(y_mm))
    else:
        offsets = {
            "right": (offset_mm, 0.0),
            "left": (-offset_mm, 0.0),
            "up": (0.0, offset_mm),
            "down": (0.0, -offset_mm),
        }
        if direction not in offsets:
            raise InvalidParameterError(
                f"unknown projection direction {direction!r}",
                available=sorted(offsets),
            )
        try:
            current = [float(value) for value in binding.value(parent.Position)]
        except Exception:
            current = [0.0, 0.0]
        position = (
            current[0] + units.mm_to_m(offsets[direction][0]),
            current[1] + units.mm_to_m(offsets[direction][1]),
        )
    before = {_view_name(view) for view in _views(doc)}
    drawing = _drawing(doc)
    if not drawing.ActivateView(parent_name):
        raise ComCallError(f"SOLIDWORKS could not activate parent view {parent_name!r}")
    # Measured on SW2026 SP0.0: CreateUnfoldedViewAt3 projects from the
    # SELECTED view, not the active one; activation alone silently returns
    # None. Selecting the view is what the UI does before "Projected View".
    session.clear_selection(doc)
    if not _extension(doc).SelectByID2(
        parent_name, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0
    ):
        raise SelectionError(
            f"could not select parent view {parent_name!r}",
            hint="Use a model view name from list_drawing_views.",
        )
    view = drawing.CreateUnfoldedViewAt3(
        position[0], position[1], 0.0, bool(not_aligned)
    )
    if view is None:
        # Re-select after activation in case the selection was cleared.
        drawing.ActivateView(parent_name)
        _extension(doc).SelectByID2(
            parent_name, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0
        )
        view = drawing.CreateUnfoldedViewAt3(
            position[0], position[1], 0.0, bool(not_aligned)
        )
    session.clear_selection(doc)
    if view is None:
        raise ComCallError(
            f"SOLIDWORKS did not project a view from {parent_name!r}",
            hint="Create projected views before adding sheets; a second "
            "sheet or an unselectable parent view makes the call return "
            "nothing.",
        )
    created = _view_name(view)
    if created in before or created == parent_name:
        raise VerificationError(
            "the projected view was not added to the drawing", view=created
        )
    return {
        "data": {
            "parent": parent_name,
            "view": _view_info(view),
            "position_mm": [
                round(units.m_to_mm(position[0]), 4),
                round(units.m_to_mm(position[1]), 4),
            ],
        },
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def insert_section_view(
    parent_view: str | None = None,
    x1_mm: float | None = None,
    y1_mm: float | None = None,
    x2_mm: float | None = None,
    y2_mm: float | None = None,
    place_x_mm: float = 0.0,
    place_y_mm: float = 0.0,
    label: str = "A",
    not_aligned: bool = False,
    exclude_fasteners: bool = False,
    depth_mm: float = 0.0,
) -> dict:
    """Create a section view: the cutting line is drawn in the parent view.

    Coordinates are sheet millimetres; read the parent view's position from
    list_drawing_views first. Options come from this build's typelib
    (swCreateSectionViewAtOptions_e: 1 = not aligned, 64 = exclude fasteners).
    """
    _, doc, _ = session.active_doc(("drawing",))
    for key, value in (
        ("x1_mm", x1_mm), ("y1_mm", y1_mm), ("x2_mm", x2_mm), ("y2_mm", y2_mm),
    ):
        if value is None:
            raise InvalidParameterError(f"{key} is required for a section view")
    parent = _model_view(doc, parent_view)
    parent_name = _view_name(parent)
    # The caller thinks in sheet millimetres; the view sketch does not.
    local_x1, local_y1 = _to_view_sketch_mm(parent, x1_mm, y1_mm)
    local_x2, local_y2 = _to_view_sketch_mm(parent, x2_mm, y2_mm)
    _draw_in_view(
        doc,
        parent_name,
        lambda sm: sm.CreateLine(
            units.mm_to_m(local_x1), units.mm_to_m(local_y1), 0.0,
            units.mm_to_m(local_x2), units.mm_to_m(local_y2), 0.0,
        ),
    )
    options = 0
    if not_aligned:
        options |= SECTION_OPTIONS["not_aligned"]
    if exclude_fasteners:
        options |= SECTION_OPTIONS["exclude_fasteners"]
    view = _drawing(doc).CreateSectionViewAt5(
        units.mm_to_m(place_x_mm),
        units.mm_to_m(place_y_mm),
        0.0,
        str(label),
        options,
        None,
        units.mm_to_m(depth_mm),
    )
    if view is None:
        raise ComCallError(
            "SOLIDWORKS did not create the section view",
            hint="Check that the cutting line crosses the parent view's geometry.",
            parent=parent_name,
        )
    section_view = binding.wrap(view, "IView")
    rebuild_state = inspect.rebuild(doc)
    # Measured: a section created from a misplaced cutting line is still created
    # (labelled `section`, correct outline) but is never cut, so the return
    # value proves nothing. A real cut exposes line edges of its contour; an
    # uncut one exposes only the parent's curves.
    visible = _view_visible_edges(section_view)
    cut_edges = [
        info
        for info in (_view_edge_info(entity) for entity in visible)
        if info.get("kind") == "line"
    ]
    if not cut_edges:
        raise VerificationError(
            "the section view was created but exposes no cut edges",
            hint="The cutting line may miss the parent view's geometry, or the "
            "cut produces curved contours only; check the parent view's "
            "position and the cutting line's sheet coordinates.",
            parent=parent_name,
            label=str(label),
            visible_edges=len(visible),
        )
    return {
        "data": {
            "parent": parent_name,
            "view": _view_info(section_view),
            "label": str(label),
            "cut_edges": len(cut_edges),
        },
        "evidence": {"rebuild": rebuild_state, "cut_edges": len(cut_edges)},
    }


def insert_detail_view(
    parent_view: str | None = None,
    center_x_mm: float | None = None,
    center_y_mm: float | None = None,
    radius_mm: float | None = None,
    place_x_mm: float = 0.0,
    place_y_mm: float = 0.0,
    label: str = "I",
    scale_numerator: float = 2,
    scale_denominator: float = 1,
    full_outline: bool = False,
    jagged_outline: bool = False,
) -> dict:
    """Create a detail view: the detail circle is drawn in the parent view.

    The scale is absolute (model to paper), not relative to the parent, so
    pick a scale near the sheet scale or the detail overflows the sheet.
    """
    _, doc, _ = session.active_doc(("drawing",))
    for key, value in (
        ("center_x_mm", center_x_mm), ("center_y_mm", center_y_mm),
        ("radius_mm", radius_mm),
    ):
        if value is None:
            raise InvalidParameterError(f"{key} is required for a detail view")
    if radius_mm <= 0 or scale_numerator <= 0 or scale_denominator <= 0:
        raise InvalidParameterError("radius and detail scale must be positive")
    parent = _model_view(doc, parent_view)
    parent_name = _view_name(parent)
    local_x, local_y = _to_view_sketch_mm(parent, center_x_mm, center_y_mm)
    _draw_in_view(
        doc,
        parent_name,
        lambda sm: sm.CreateCircleByRadius(
            units.mm_to_m(local_x), units.mm_to_m(local_y), 0.0,
            units.mm_to_m(radius_mm),
        ),
    )
    view = _drawing(doc).CreateDetailViewAt4(
        units.mm_to_m(place_x_mm),
        units.mm_to_m(place_y_mm),
        0.0,
        DETAIL_CIRCLE_STYLES["circle"],
        float(scale_numerator),
        float(scale_denominator),
        str(label),
        DETAIL_VIEW_STYLES["leader"],
        bool(full_outline),
        bool(jagged_outline),
        False,
        0,
    )
    if view is None:
        raise ComCallError(
            "SOLIDWORKS did not create the detail view",
            hint="Check that the detail circle lies over the parent view's geometry.",
            parent=parent_name,
        )
    return {
        "data": {
            "parent": parent_name,
            "view": _view_info(binding.wrap(view, "IView")),
            "label": str(label),
        },
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def create_sketch(view_name: str | None = None) -> dict:
    """Open a sketch in a drawing view.

    Used to define section/detail boundaries or to draw annotation geometry
    with the normal sketch tools; close it with exit_sketch.
    """
    _, doc, _ = session.active_doc(("drawing",))
    resolved = _view_name(_model_view(doc, view_name))
    if not _drawing(doc).ActivateView(resolved):
        raise ComCallError(f"SOLIDWORKS could not activate view {resolved!r}")
    session.clear_selection(doc)
    manager = sketch._sketch_manager(doc)
    manager.InsertSketch(True)
    if manager.ActiveSketch is None:
        raise ComCallError(f"SOLIDWORKS did not open a sketch in view {resolved!r}")
    return {
        "data": {"view": resolved, "active_sketch": True},
        "evidence": {"active_sketch": True, "view": resolved},
    }


def _select_circular_edges(doc, view) -> int:
    """Select every circular edge visible in the view.

    InsertCenterMark3/InsertCenterLine2 annotate the current selection rather
    than the whole view. Drawing selection goes through IView.SelectEntity;
    selecting the underlying model edges would select the model instead.
    """
    session.clear_selection(doc)
    entities = None
    try:
        entities = view.GetVisibleEntities2(None, VIEW_ENTITY_EDGES)
    except Exception:
        entities = None
    count = 0
    for entity in entities or []:
        try:
            curve = entity.GetCurve()
            if curve is None or int(binding.value(curve.Identity)) != CURVE_IDENTITY_CIRCLE:
                continue
            if view.SelectEntity(entity, True):
                count += 1
        except Exception:
            continue
    return count


def _annotation_type_counts(
    doc,
    view_name: str | None,
    sheet_name: str | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in list_annotations(view_name, sheet_name)["views"]:
        for annotation in item["annotations"]:
            kind = annotation["type"]
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def insert_center_marks(
    view_name: str | None = None,
    style: str = "single",
    propagate: bool = True,
    slots: bool = False,
    selected_only: bool = False,
) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    if style not in CENTER_MARK_STYLES:
        raise InvalidParameterError(
            f"unknown center mark style {style!r}",
            available=sorted(CENTER_MARK_STYLES),
        )
    resolved = _view_name(_model_view(doc, view_name))
    if not _drawing(doc).ActivateView(resolved):
        raise ComCallError(f"SOLIDWORKS could not activate view {resolved!r}")
    mark_types = (
        CENTER_MARK_TYPES["holes"] | CENTER_MARK_TYPES["fillets"] | CENTER_MARK_TYPES["slots"]
    )
    active_sheet = _sheet_name(_current_sheet(doc))
    before = _annotation_type_counts(doc, resolved, active_sheet)
    if selected_only:
        view = _model_view(doc, resolved)
        picked = _select_circular_edges(doc, view)
        marks = _drawing(doc).InsertCenterMark3(
            CENTER_MARK_STYLES[style], bool(propagate), bool(slots)
        )
        added_flag = bool(marks)
        method = "InsertCenterMark3"
    else:
        view = _model_view(doc, resolved)
        # swAutoInsertCenterMarkOptions bits 1|2|8 = linear, circular and base
        # connection lines; documented per-method, no typelib enum on this build.
        added_flag = bool(
            view.AutoInsertCenterMarks2(
                mark_types,
                1 | 2 | 8,
                bool(slots),
                bool(slots),
                True,
                0.0,
                0.0,
                False,
                False,
                0.0,
            )
        )
        picked = 0
        method = "AutoInsertCenterMarks2"
    session.clear_selection(doc)
    evidence = {"rebuild": inspect.rebuild(doc)}
    after = _annotation_type_counts(doc, resolved, active_sheet)
    marks_added = after.get("center_mark", 0) - before.get("center_mark", 0)
    centerlines_added = after.get("centerline", 0) - before.get("centerline", 0)
    added = marks_added + centerlines_added
    if added <= 0:
        raise VerificationError(
            "SOLIDWORKS added no center marks",
            view=resolved,
            hint="The view may have no holes, fillets or slots to mark.",
        )
    return {
        "data": {
            "view": resolved,
            "method": method,
            "marks_added": marks_added,
            "centerlines_added": centerlines_added,
            "center_annotations_added": added,
            "circles_selected": picked,
        },
        "evidence": evidence,
    }


def insert_centerlines(view_name: str | None = None, selected_only: bool = False) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    resolved = _view_name(_model_view(doc, view_name))
    if not _drawing(doc).ActivateView(resolved):
        raise ComCallError(f"SOLIDWORKS could not activate view {resolved!r}")
    active_sheet = _sheet_name(_current_sheet(doc))
    before = _annotation_type_counts(doc, resolved, active_sheet)
    if selected_only:
        view = _model_view(doc, resolved)
        picked = _select_circular_edges(doc, view)
        lines = _drawing(doc).InsertCenterLine2()
        count = len(lines or [])
        method = "InsertCenterLine2"
    else:
        view = _model_view(doc, resolved)
        # In a drawing the axes of circular holes are automatic center marks,
        # not standalone ICenterLine objects; InsertCenterLine2 on raw model
        # edges silently does nothing in a part view.
        view.AutoInsertCenterMarks2(
            CENTER_MARK_TYPES["holes"],
            1 | 2 | 8,
            False,
            False,
            True,
            0.0,
            0.0,
            False,
            False,
            0.0,
        )
        picked = 0
        count = None
        method = "AutoInsertCenterMarks2"
    session.clear_selection(doc)
    evidence = {"rebuild": inspect.rebuild(doc)}
    after = _annotation_type_counts(doc, resolved, active_sheet)
    centerlines_added = after.get("centerline", 0) - before.get("centerline", 0)
    marks_added = after.get("center_mark", 0) - before.get("center_mark", 0)
    added = centerlines_added + marks_added
    if added <= 0:
        raise VerificationError("SOLIDWORKS added no centerlines", view=resolved)
    return {
        "data": {
            "view": resolved,
            "method": method,
            "centerlines_added": centerlines_added,
            "center_marks_added": marks_added,
            "center_annotations_added": added,
            "circles_selected": picked,
        },
        "evidence": evidence,
    }


def _model_view(doc, name: str | None = None):
    """Return a model view (never the sheet) by name or the first one."""
    active_sheet = _sheet_name(_current_sheet(doc))
    views = _views(doc, active_sheet)
    for view in views:
        view_name = _view_name(view)
        if name is not None and view_name != name:
            continue
        try:
            if int(binding.value(view.Type)) == 1:
                if name is not None:
                    raise SelectionError(
                        f"drawing view {name!r} is the sheet view, not a model view",
                        hint="Choose a model view from list_drawing_views.",
                    )
                continue
        except SelectionError:
            raise
        except Exception:
            pass
        return view
    if name is not None:
        raise SelectionError(
            f"drawing view {name!r} not found",
            available=[_view_name(view) for view in views],
        )
    raise SelectionError(
        "no model view on the active drawing",
        hint="Call drawing_insert_view or drawing_insert_standard_views first.",
    )


def _dimension_total(doc) -> int:
    total = 0
    active_sheet = _sheet_name(_current_sheet(doc))
    for view in _views(doc, active_sheet):
        try:
            total += int(view.GetDimensionCount())
        except Exception:
            continue
    return total


def insert_model_annotations(
    view_name: str | None = None,
    types: list[str] | None = None,
    all_views: bool = True,
    duplicate_dimensions: bool = False,
    hidden_feature_dimensions: bool = False,
    source: str = "entire_model",
) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    chosen = [str(item) for item in (types or DEFAULT_ANNOTATION_TYPES)]
    mask = 0
    for name in chosen:
        code = ANNOTATION_TYPES.get(name)
        if code is None:
            raise InvalidParameterError(
                f"unknown annotation type {name!r}",
                available=sorted(ANNOTATION_TYPES),
            )
        mask |= code
    source_code = ANNOTATION_SOURCES.get(source)
    if source_code is None:
        raise InvalidParameterError(
            f"unknown source {source!r}", available=sorted(ANNOTATION_SOURCES)
        )
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    session.clear_selection(doc)
    drawing = _drawing(doc)
    # InsertModelAnnotations3 works on the selected drawing view; activating
    # the view is not enough (the call then silently imports nothing).
    if not _extension(doc).SelectByID2(
        resolved, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0
    ):
        raise SelectionError(f"could not select drawing view {resolved!r}")
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate drawing view {resolved!r}")
    annotation_sheet = None if all_views else _sheet_name(_current_sheet(doc))
    before_counts = _annotation_type_counts(doc, None, annotation_sheet)
    drawing.InsertModelAnnotations3(
        source_code,
        mask,
        bool(all_views),
        bool(duplicate_dimensions),
        bool(hidden_feature_dimensions),
        False,
    )
    evidence = {"rebuild": inspect.rebuild(doc)}
    session.clear_selection(doc)
    after_counts = _annotation_type_counts(doc, None, annotation_sheet)
    added_by_type = {
        kind: after_counts.get(kind, 0) - before_counts.get(kind, 0)
        for kind in set(before_counts) | set(after_counts)
        if after_counts.get(kind, 0) - before_counts.get(kind, 0) > 0
    }
    expected_types = set().union(
        *(ANNOTATION_RESULT_TYPES.get(name, set()) for name in chosen)
    )
    added = sum(added_by_type.get(kind, 0) for kind in expected_types)
    if not expected_types:
        added = sum(added_by_type.values())
    if added <= 0:
        raise VerificationError(
            "no model items were imported",
            hint="On this build InsertModelAnnotations3 can return nothing even "
            "when the model has dimensions; use drawing_auto_dimension to "
            "generate dimensions from the view geometry instead.",
        )
    return {
        "data": {
            "view": resolved,
            "types": chosen,
            "annotations_added_count": added,
            "dimensions_added": added_by_type.get("dimension", 0),
            "dimensions_total": _dimension_total(doc),
            "annotation_counts_before": before_counts,
            "annotation_counts_after": after_counts,
            "annotations_added": added_by_type,
        },
        "evidence": evidence,
    }


def auto_dimension(
    view_name: str | None = None,
    horizontal_scheme: str = "baseline",
    vertical_scheme: str = "baseline",
    horizontal_placement: str = "below",
    vertical_placement: str = "left",
    arrange: bool = True,
) -> dict:
    """Run DimXpert over a view and generate dimensions from its geometry."""
    _, doc, _ = session.active_doc(("drawing",))
    scheme_h = AUTODIM_SCHEMES.get(horizontal_scheme)
    scheme_v = AUTODIM_SCHEMES.get(vertical_scheme)
    if scheme_h is None or scheme_v is None:
        raise InvalidParameterError(
            "unknown dimension scheme", available=sorted(AUTODIM_SCHEMES)
        )
    placement_h = AUTODIM_HORIZONTAL.get(horizontal_placement)
    placement_v = AUTODIM_VERTICAL.get(vertical_placement)
    if placement_h is None or placement_v is None:
        raise InvalidParameterError(
            "horizontal_placement must be below/above and vertical_placement "
            "left/right"
        )
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate drawing view {resolved!r}")
    # DimXpert dimensions the selected drawing view, not the activated one:
    # without an explicit selection it silently acts on whichever view it
    # likes (InsertModelAnnotations3 has the same quirk).
    session.clear_selection(doc)
    if not _extension(doc).SelectByID2(
        resolved, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0
    ):
        raise SelectionError(f"could not select drawing view {resolved!r}")
    before = _dimension_total(doc)
    status = drawing.AutoDimension(
        AUTODIM_ENTITIES["all"],
        scheme_h,
        placement_h,
        scheme_v,
        placement_v,
    )
    session.clear_selection(doc)
    evidence = {"rebuild": inspect.rebuild(doc)}
    after = _dimension_total(doc)
    added = after - before
    if added <= 0:
        raise VerificationError(
            "auto-dimensioning added no dimensions",
            hint="Make sure the view actually shows model geometry.",
            status=int(status) if status is not None else None,
        )
    result = {
        "data": {
            "view": resolved,
            "dimensions_added": added,
            "dimensions_total": after,
            "status": int(status) if status is not None else None,
        },
        "evidence": evidence,
    }
    if arrange:
        # DimXpert's rows collide at the default text height; re-space them.
        try:
            result["data"]["arranged"] = arrange_dimensions(resolved)["data"]
        except Exception as exc:
            raise VerificationError(
                "auto-dimensioning succeeded but dimension arrangement failed",
                view=resolved,
                dimensions_added=added,
                cause=str(exc),
            ) from exc
    return result


def add_note(
    text: str,
    x_mm: float,
    y_mm: float,
    height_mm: float | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    session.clear_selection(doc)
    raw = doc.InsertNote(str(text))
    if raw is None:
        raise ComCallError("SOLIDWORKS did not create the note")
    result = {"text": str(text), "x_mm": x_mm, "y_mm": y_mm}
    positioned = False
    try:
        note = binding.wrap(raw, "INote")
        annotation = binding.wrap(note.GetAnnotation(), "IAnnotation")
    except Exception:
        annotation = None
    if annotation is not None:
        try:
            annotation.SetPosition(units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0)
            measured_position = list(binding.value(annotation.GetPosition()) or [])
            positioned = len(measured_position) >= 2 and all(
                abs(float(actual) - float(expected)) <= units.mm_to_m(0.1)
                for actual, expected in zip(
                    measured_position[:2],
                    (units.mm_to_m(x_mm), units.mm_to_m(y_mm)),
                )
            )
            result["positioned"] = positioned
            if len(measured_position) >= 2:
                result["position_mm"] = [
                    round(units.m_to_mm(measured_position[0]), 3),
                    round(units.m_to_mm(measured_position[1]), 3),
                ]
        except Exception:
            result["positioned"] = False
        if height_mm:
            try:
                # Measured on SW2026 SP0.0: IAnnotation.GetTextFormat with no
                # argument raises "Type mismatch"; INote.GetTextFormat works.
                text_format = binding.wrap(note.GetTextFormat(), "ITextFormat")
                text_format.CharHeight = units.mm_to_m(height_mm)
                note.SetTextFormat(0, text_format)
                measured_height = float(
                    binding.value(
                        binding.wrap(note.GetTextFormat(), "ITextFormat").CharHeight
                    )
                )
                result["height_mm"] = round(units.m_to_mm(measured_height), 3)
            except Exception as exc:
                raise VerificationError(
                    "SOLIDWORKS did not apply the note height",
                    height_mm=height_mm,
                    error=f"{type(exc).__name__}: {exc}",
                ) from exc
    if not positioned:
        raise VerificationError(
            "SOLIDWORKS created the note but did not confirm its position",
            expected_position_mm=[x_mm, y_mm],
        )
    return {
        "data": result,
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def list_annotations(
    view_name: str | None = None,
    sheet_name: str | None = None,
) -> dict:
    """Read back every annotation on the drawing, with note text.

    This is the verification half of the annotation tools: dimension and note
    counts come from the API rather than from the insertion call.
    """
    _, doc, _ = session.active_doc(("drawing",))
    property_map: dict[str, str] | None = None
    try:
        property_map = {
            name: value
            for name, value in (list_properties().get("properties") or {}).items()
        }
    except Exception:
        property_map = None
    try:
        model_map = _referenced_property_map()
    except Exception:
        model_map = None
    system_map = _system_property_map(doc)
    views = []
    for view in _views(doc, sheet_name):
        name = _view_name(view)
        if view_name is not None and name != view_name:
            continue
        annotations = []
        try:
            current = view.GetFirstAnnotation()
        except Exception:
            current = None
        guard = 0
        while current is not None and guard < 5000:
            guard += 1
            try:
                annotation = binding.wrap(current, "IAnnotation")
            except Exception:
                break
            info = {"type": "other", "index": len(annotations)}
            try:
                kind = int(annotation.GetType())
                info["type"] = ANNOTATION_TYPE_NAMES.get(kind, f"type_{kind}")
            except Exception:
                pass
            try:
                info["visible"] = bool(binding.value(annotation.Visible))
            except Exception:
                pass
            try:
                position = list(annotation.GetPosition())
                if len(position) >= 2:
                    info["position_mm"] = [
                        round(units.m_to_mm(position[0]), 3),
                        round(units.m_to_mm(position[1]), 3),
                    ]
            except Exception:
                pass
            if info["type"] == "dimension":
                try:
                    specific = annotation.GetSpecificAnnotation()
                    dimension = binding.wrap(specific, "IDisplayDimension")
                    info["text"] = _dimension_text(dimension)
                    info["show_dimension_value"] = bool(
                        binding.value(dimension.ShowDimensionValue)
                    )
                    value = _dimension_value(dimension)
                    if value is not None:
                        info["value"] = round(value, 6)
                    prefix = str(dimension.GetText(1) or "")
                    suffix = str(dimension.GetText(2) or "")
                    if prefix or suffix:
                        info["prefix"] = prefix
                        info["suffix"] = suffix
                        if value is not None:
                            info["reading"] = f"{prefix}{value}{suffix}"
                    tolerance = _tolerance_info(dimension)
                    if tolerance:
                        info["tolerance"] = tolerance
                    if bool(binding.value(dimension.IsHoleCallout)):
                        info["is_hole_callout"] = True
                except Exception:
                    pass
            elif info["type"] == "note":
                try:
                    # The annotation dispatch itself does not QueryInterface
                    # to INote; GetSpecificAnnotation does.
                    specific = annotation.GetSpecificAnnotation()
                    note = binding.wrap(specific, "INote")
                    info.update(_note_info(note, property_map, model_map, system_map))
                except Exception:
                    pass
            elif info["type"] == "datum_tag":
                try:
                    specific = annotation.GetSpecificAnnotation()
                    tag = binding.wrap(specific, "IDatumTag")
                    info["label"] = str(binding.value(tag.GetLabel) or "")
                except Exception:
                    pass
            elif info["type"] == "geometric_tolerance":
                try:
                    specific = annotation.GetSpecificAnnotation()
                    gtol = binding.wrap(specific, "IGtol")
                    info["frame_values"] = [
                        str(item)
                        for item in binding.value(gtol.GetFrameValues(1)) or []
                    ]
                    info["frame_symbols"] = [
                        int(item)
                        for item in binding.value(gtol.GetFrameSymbols(1)) or []
                    ]
                except Exception:
                    pass
            elif info["type"] == "surface_finish":
                try:
                    specific = annotation.GetSpecificAnnotation()
                    sf = binding.wrap(specific, "ISFSymbol")
                    # Measured: GetTextCount() reports 0 while GetText(0..6)
                    # holds MachAllowance(1)/OtherVals(4)/MaxRoughness(5)/
                    # MinRoughness(6); the displayed value is MaxRoughness.
                    texts = [str(sf.GetText(index) or "") for index in range(7)]
                    info["texts"] = texts
                    info["text"] = next((text for text in texts if text), "")
                except Exception:
                    pass
            annotations.append(info)
            try:
                current = annotation.GetNext()
            except Exception:
                break
        views.append(
            {
                "name": name,
                "sheet_name": _view_sheet_name(view),
                "annotations": annotations,
                "count": len(annotations),
            }
        )
    return {
        "views": views,
        "total": sum(item["count"] for item in views),
        "sheet": sheet_name,
    }


# ---------------------------------------------------------------------------
# Annotation and view editing
# ---------------------------------------------------------------------------


def _named_view(doc, view_name: str):
    """Any view on the active sheet by exact name, including the sheet view."""
    active_sheet = _sheet_name(_current_sheet(doc))
    views = _views(doc, active_sheet)
    for view in views:
        if _view_name(view) == str(view_name):
            return view
    raise SelectionError(
        f"drawing view {view_name!r} not found",
        available=[_view_name(view) for view in views],
    )


def _annotation_at(view, index):
    """The nth annotation of a view, in list_drawing_annotations order."""
    try:
        position = int(index)
    except (TypeError, ValueError) as exc:
        raise InvalidParameterError("index must be an integer") from exc
    if position < 0:
        raise InvalidParameterError("index must be zero or greater")
    for order, annotation in enumerate(_view_annotations(view)):
        if order == position:
            return annotation
    raise SelectionError(
        f"annotation index {position} is out of range in {_view_name(view)!r}",
        hint="Re-list with list_drawing_annotations; indexes shift after edits.",
    )


def _annotation_kind(annotation) -> str:
    try:
        return ANNOTATION_TYPE_NAMES.get(int(annotation.GetType()), "other")
    except Exception:
        return "other"


def move_annotation(view_name: str, index: int, x_mm: float, y_mm: float) -> dict:
    """Move one annotation (note or dimension) to a sheet position.

    Position is millimetres from the sheet's lower-left corner, the same
    anchor ``list_drawing_annotations`` reports. Measured on SW2026 SP0.0:
    ``IAnnotation.SetPosition`` moves notes and dimensions, and the read-back
    follows within 0.1 mm.
    """
    _, doc, _ = session.active_doc(("drawing",))
    view = _named_view(doc, view_name)
    annotation = _annotation_at(view, index)
    kind = _annotation_kind(annotation)
    annotation.SetPosition(units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0)
    measured = list(binding.value(annotation.GetPosition()) or [])
    moved = len(measured) >= 2 and all(
        abs(float(actual) - units.mm_to_m(expected)) <= units.mm_to_m(0.1)
        for actual, expected in zip(measured[:2], (x_mm, y_mm))
    )
    if not moved:
        raise VerificationError(
            "SOLIDWORKS did not move the annotation",
            expected_mm=[x_mm, y_mm],
            measured_mm=[round(units.m_to_mm(value), 3) for value in measured[:2]],
        )
    session.clear_selection(doc)
    return {
        "data": {
            "view": _view_name(view),
            "index": int(index),
            "type": kind,
            "position_mm": [round(units.m_to_mm(value), 3) for value in measured[:2]],
        },
        "evidence": {"annotations": list_annotations(_view_name(view))},
    }


def delete_annotation(view_name: str, index: int) -> dict:
    """Delete one annotation after selecting it.

    Measured on SW2026 SP0.0: ``IAnnotation.Select3(True, None)`` returns
    false and the delete is a no-op; ``IAnnotation.Select(True)`` selects the
    annotation and ``IModelDocExtension.DeleteSelection2`` removes it.
    """
    _, doc, _ = session.active_doc(("drawing",))
    view = _named_view(doc, view_name)
    annotation = _annotation_at(view, index)
    kind = _annotation_kind(annotation)
    before = sum(1 for _ in _view_annotations(view))
    session.clear_selection(doc)
    if not annotation.Select(True):
        raise SelectionError(
            f"SOLIDWORKS refused to select annotation {index} in {_view_name(view)!r}"
        )
    removed = bool(doc.Extension.DeleteSelection2(0))
    after = sum(1 for _ in _view_annotations(view))
    if after >= before:
        raise VerificationError(
            "SOLIDWORKS did not delete the annotation",
            selected=True,
            delete_return=removed,
            hint="The annotation may be referenced by a view SOLIDWORKS keeps.",
        )
    return {
        "data": {
            "view": _view_name(view),
            "index": int(index),
            "type": kind,
            "deleted": True,
            "remaining": after,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "annotations": list_annotations(_view_name(view)),
        },
    }


def set_annotation_text(
    view_name: str,
    index: int,
    text: str | None = None,
    prefix: str | None = None,
    suffix: str | None = None,
    height_mm: float | None = None,
) -> dict:
    """Edit the text of a note or a dimension override.

    Notes take ``text`` (full replacement). Dimensions take ``prefix`` and/or
    ``suffix``: measured on SW2026 SP0.0, ``IDisplayDimension.SetText(0, ...)``
    (``swDimensionTextAll``) is a no-op, while prefix (1) and suffix (2) write
    and read back.
    """
    _, doc, _ = session.active_doc(("drawing",))
    view = _named_view(doc, view_name)
    annotation = _annotation_at(view, index)
    kind = _annotation_kind(annotation)
    data: dict = {
        "view": _view_name(view),
        "index": int(index),
        "type": kind,
    }
    if kind == "note":
        if text is None:
            raise InvalidParameterError(
                "text is required for a note",
                hint="Notes take full text; prefix/suffix are for dimensions.",
            )
        note = binding.wrap(annotation.GetSpecificAnnotation(), "INote")
        note.SetText(str(text))
        measured = str(binding.value(note.GetText) or "")
        if measured != str(text):
            raise VerificationError(
                "SOLIDWORKS did not retain the note text",
                expected=str(text),
                measured=measured,
            )
        data["text"] = measured
        if height_mm is not None:
            # Measured on SW2026 SP0.0: IAnnotation.GetTextFormat with no
            # argument raises "Type mismatch"; INote.GetTextFormat (or the
            # indexed IAnnotation.GetTextFormat(0)) works and the height
            # reads back.
            text_format = binding.wrap(note.GetTextFormat(), "ITextFormat")
            text_format.CharHeight = units.mm_to_m(height_mm)
            note.SetTextFormat(0, text_format)
            measured_height = float(
                binding.value(
                    binding.wrap(note.GetTextFormat(), "ITextFormat").CharHeight
                )
            )
            if abs(measured_height - units.mm_to_m(height_mm)) > units.mm_to_m(0.01):
                raise VerificationError(
                    "SOLIDWORKS did not apply the note height",
                    expected_mm=height_mm,
                    measured_mm=round(units.m_to_mm(measured_height), 4),
                )
            data["height_mm"] = round(units.m_to_mm(measured_height), 3)
    elif kind == "dimension":
        if text is not None:
            raise InvalidParameterError(
                "use prefix/suffix for a dimension",
                hint="SetText(0, ...) is a measured no-op on SW2026 SP0.0; "
                "prefix (1) and suffix (2) work.",
            )
        if prefix is None and suffix is None:
            raise InvalidParameterError("provide prefix and/or suffix")
        dimension = binding.wrap(
            annotation.GetSpecificAnnotation(), "IDisplayDimension"
        )
        for label, which, value in (("prefix", 1, prefix), ("suffix", 2, suffix)):
            if value is None:
                continue
            dimension.SetText(which, str(value))
            measured = str(dimension.GetText(which) or "")
            if measured != str(value):
                raise VerificationError(
                    f"SOLIDWORKS did not retain the dimension {label}",
                    expected=str(value),
                    measured=measured,
                )
            data[label] = measured
    else:
        raise InvalidParameterError(
            f"text editing supports notes and dimensions, not {kind}",
            hint="Datum, GTol and surface-finish symbols have their own tools.",
        )
    session.clear_selection(doc)
    return {
        "data": data,
        "evidence": {"annotations": list_annotations(_view_name(view))},
    }


def _dimension_fingerprint(info: dict) -> tuple:
    position = info.get("position_mm") or []
    return (
        info.get("kind"),
        round(float(info["value"]), 6) if info.get("value") is not None else None,
        tuple(round(float(value), 3) for value in position[:2]),
    )


def add_dimension(
    view_name: str | None = None,
    edge_indices: list[int] | None = None,
    placement_mm: list[float] | None = None,
) -> dict:
    """Dimension picked view edges: one edge for its size, two for a distance.

    Edge indices come from ``list_drawing_view_edges``; ``placement_mm`` is
    where the dimension text sits on the sheet. The dimension measures the
    geometry and does not drive it. Measured on SW2026 SP0.0: two circular
    edges produce a linear centre-distance dimension and one circle its
    diameter, both readable through ``list_dimensions``.
    """
    if not edge_indices:
        raise InvalidParameterError(
            "edge_indices is required", hint="Call list_drawing_view_edges first."
        )
    indices = [int(item) for item in edge_indices]
    if len(indices) > 2:
        raise InvalidParameterError("one or two edges per dimension")
    if placement_mm is None or len(placement_mm) < 2:
        raise InvalidParameterError("placement_mm must be [x_mm, y_mm]")
    x_mm, y_mm = float(placement_mm[0]), float(placement_mm[1])
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    entities = _view_visible_edges(view)
    for position in indices:
        if position < 0 or position >= len(entities):
            raise SelectionError(
                f"edge index {position} is out of range",
                view=resolved,
                available=len(entities),
                hint="Re-list with list_drawing_view_edges.",
            )
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    session.clear_selection(doc)
    for order, position in enumerate(indices):
        if not view.SelectEntity(entities[position], bool(order)):
            raise SelectionError(
                f"could not select edge {position} in view {resolved!r}"
            )
    before = [
        _dimension_fingerprint(_dimension_entry_info(annotation, display))
        for annotation, display in _view_dimension_entries(view)
    ]
    restore = sketch._suppress_dimension_dialog()
    try:
        raw = doc.AddDimension2(units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0)
    finally:
        sketch._restore_dimension_dialog(restore)
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not create a dimension for that selection",
            hint="Pick one circular edge for its diameter or two compatible "
            "edges for a distance.",
        )
    entries = list(_view_dimension_entries(view))
    fresh = [
        (order, _dimension_entry_info(annotation, display))
        for order, (annotation, display) in enumerate(entries)
        if _dimension_fingerprint(_dimension_entry_info(annotation, display))
        not in before
    ]
    if len(fresh) == 1:
        index, info = fresh[0]
    elif entries:
        index = len(entries) - 1
        info = _dimension_entry_info(*entries[index])
    else:
        index, info = None, {}
    session.clear_selection(doc)
    return {
        "data": {
            "view": resolved,
            "edge_indices": indices,
            "placement_mm": [x_mm, y_mm],
            "index": index,
            "kind": info.get("kind"),
            "value": info.get("value"),
            "position_mm": info.get("position_mm"),
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "dimensions": list_dimensions(resolved),
        },
    }


def delete_view(name: str) -> dict:
    """Delete a model view; the sheet view itself cannot be deleted.

    Measured on SW2026 SP0.0: ``SelectByID2(name, "DRAWINGVIEW", ...)`` then
    ``IModelDocExtension.DeleteSelection2`` removes the view. Dependent
    projected/section/detail views SOLIDWORKS decides to remove are reported
    in ``removed_views``.
    """
    if not str(name).strip():
        raise InvalidParameterError("name must not be empty")
    _, doc, _ = session.active_doc(("drawing",))
    if str(name) in _sheet_names(doc):
        raise InvalidParameterError(
            f"{name!r} is a sheet, not a view; sheets cannot be deleted",
            hint="Use drawing_add_sheet to add sheets; documents are closed, not sheets.",
        )
    active_sheet = _sheet_name(_current_sheet(doc))
    view = None
    for candidate in _views(doc, active_sheet):
        if _view_name(candidate) == str(name):
            view = candidate
            break
    if view is None:
        raise SelectionError(
            f"drawing view {name!r} not found",
            available=[_view_name(item) for item in _views(doc, active_sheet)],
        )
    try:
        if int(binding.value(view.Type)) == 1:
            raise InvalidParameterError(
                "the sheet view cannot be deleted",
                hint="Delete the sheet with the document, or clear its views.",
            )
    except InvalidParameterError:
        raise
    except Exception:
        pass
    before = [_view_name(item) for item in _views(doc, active_sheet)]
    extension = doc.Extension
    selected = bool(
        extension.SelectByID2(
            str(name), "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, None, 0
        )
    )
    if not selected:
        outline = list(binding.value(view.GetOutline()) or [])
        if len(outline) >= 4:
            selected = bool(
                extension.SelectByID2(
                    "",
                    "DRAWINGVIEW",
                    (float(outline[0]) + float(outline[2])) / 2.0,
                    (float(outline[1]) + float(outline[3])) / 2.0,
                    0.0,
                    False,
                    0,
                    None,
                    0,
                )
            )
    if not selected:
        raise SelectionError(
            f"could not select drawing view {name!r} for deletion",
            hint="Re-list with list_drawing_views and use the exact name.",
        )
    removed = bool(extension.DeleteSelection2(0))
    after = [_view_name(item) for item in _views(doc, active_sheet)]
    if str(name) in after:
        raise VerificationError(
            "SOLIDWORKS did not delete the drawing view",
            selected=True,
            delete_return=removed,
        )
    return {
        "data": {
            "deleted": str(name),
            "delete_return": removed,
            "removed_views": [item for item in before if item not in after],
            "remaining_views": after,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "views": list_drawing_views(active_sheet),
        },
    }


# ---------------------------------------------------------------------------
# Dimension arrangement
# ---------------------------------------------------------------------------


def plan_dimension_arrangement(
    outline_m: list[float],
    dimensions: list[dict],
    spacing_m: float,
    margin_m: float,
    limits_m: dict[str, float] | None = None,
    min_spacing_m: float | None = None,
) -> list[dict]:
    """Compute tidy offsets for the linear dimensions around a view.

    Pure geometry, unit-tested without SOLIDWORKS. ``outline_m`` is
    [min_x, min_y, max_x, max_y] in sheet metres; every dimension is
    ``{"position": (x, y), "axis": "horizontal"|"vertical"}``. Dimensions
    keep the side of the view they were on, their stacking order follows the
    distance they started at (so the innermost stays innermost), and rows sit
    a fixed distance apart. Only the coordinate perpendicular to the
    dimension line changes, which is what keeps extension lines attached.

    ``limits_m`` maps each side to the free distance before the next view or
    the sheet border. A group moves to the opposite side when its side has no
    room and the opposite side does; otherwise the spacing compresses (never
    below ``min_spacing_m``, defaulting to 60% of ``spacing_m``).
    """
    min_x, min_y, max_x, max_y = outline_m[:4]
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    opposite = {"below": "above", "above": "below", "left": "right", "right": "left"}
    if min_spacing_m is None:
        min_spacing_m = spacing_m * 0.6
    groups: dict[tuple[str, str], list[dict]] = {}
    for index, item in enumerate(dimensions):
        x, y = float(item["position"][0]), float(item["position"][1])
        if item["axis"] == "horizontal":
            side = "below" if y <= center_y else "above"
            offset = (min_y - y) if side == "below" else (y - max_y)
        else:
            side = "left" if x <= center_x else "right"
            offset = (min_x - x) if side == "left" else (x - max_x)
        groups.setdefault((item["axis"], side), []).append(
            {
                "index": index,
                "offset": offset,
                "x": x,
                "y": y,
                "original_side": side,
            }
        )
    plan: list[dict] = []
    for (axis, side), items in groups.items():
        items.sort(key=lambda entry: entry["offset"])
        used_spacing = spacing_m
        if limits_m is not None:
            needed = margin_m + (len(items) - 1) * spacing_m
            available = limits_m.get(side)
            if available is not None and available < needed:
                alternative = limits_m.get(opposite[side])
                if alternative is not None and alternative >= needed:
                    side = opposite[side]
                elif len(items) > 1:
                    room = max(available - margin_m, 0.0)
                    used_spacing = max(min_spacing_m, room / (len(items) - 1))
        for row, item in enumerate(items):
            distance = margin_m + row * used_spacing
            if axis == "horizontal":
                position = (item["x"], min_y - distance if side == "below" else max_y + distance)
            else:
                position = (min_x - distance if side == "left" else max_x + distance, item["y"])
            plan.append(
                {
                    "index": item["index"],
                    "axis": axis,
                    "side": side,
                    "original_side": item["original_side"],
                    "row": row,
                    "spacing_m": used_spacing,
                    "position": position,
                }
            )
    plan.sort(key=lambda entry: entry["index"])
    return plan


def _view_obstacle_limits(
    doc, view, outline_m: list[float], sheet_mm: list[float]
) -> dict[str, float]:
    """Free distance on each side of a view before the next view or frame.

    Only views whose span overlaps the target on the relevant axis count as
    obstacles, so a view diagonally away does not block a dimension row.
    """
    frame_margin_m = units.mm_to_m(FRAME_MARGIN_MM)
    min_x, min_y, max_x, max_y = outline_m[:4]
    width_m, height_m = units.mm_to_m(sheet_mm[0]), units.mm_to_m(sheet_mm[1])
    target_name = _view_name(view)
    below, above = min_y - frame_margin_m, height_m - frame_margin_m - max_y
    left, right = min_x - frame_margin_m, width_m - frame_margin_m - max_x
    active_sheet = _sheet_name(_current_sheet(doc))
    for other in _views(doc, active_sheet):
        if _view_name(other) == target_name:
            continue
        try:
            if int(binding.value(other.Type)) == 1:
                continue
        except Exception:
            pass
        try:
            other_outline = [float(v) for v in binding.value(other.GetOutline())]
        except Exception:
            continue
        if len(other_outline) < 4:
            continue
        o_min_x, o_min_y, o_max_x, o_max_y = other_outline[:4]
        if o_max_x > min_x and o_min_x < max_x:
            if o_max_y <= min_y:
                below = min(below, min_y - o_max_y)
            elif o_min_y >= max_y:
                above = min(above, o_min_y - max_y)
        if o_max_y > min_y and o_min_y < max_y:
            if o_max_x <= min_x:
                left = min(left, min_x - o_max_x)
            elif o_min_x >= max_x:
                right = min(right, o_min_x - max_x)
    return {
        "below": max(below, 0.0),
        "above": max(above, 0.0),
        "left": max(left, 0.0),
        "right": max(right, 0.0),
    }


def _view_linear_dimensions(view) -> list[dict]:
    """Read a view's linear dimensions with orientation and sheet position.

    IDimension.DimensionLineDirection is the reliable orientation signal on
    this build: DimXpert returns swLinearDimension (2) for both axes.
    """
    rows: list[dict] = []
    try:
        current = view.GetFirstAnnotation()
    except Exception:
        current = None
    guard = 0
    while current is not None and guard < 5000:
        guard += 1
        annotation = binding.wrap(current, "IAnnotation")
        try:
            if int(binding.value(annotation.GetType())) == 4:
                display = binding.wrap(
                    annotation.GetSpecificAnnotation(), "IDisplayDimension"
                )
                type2 = int(binding.value(display.Type2))
                if type2 in (2, 11, 12):
                    dimension = binding.wrap(display.GetDimension2(0), "IDimension")
                    vector = binding.value(dimension.DimensionLineDirection)
                    components = [float(v) for v in binding.value(vector.ArrayData)]
                    axis = (
                        "horizontal"
                        if abs(components[0]) >= abs(components[1])
                        else "vertical"
                    )
                    position = [
                        float(v) for v in binding.value(annotation.GetPosition())
                    ]
                    rows.append(
                        {"annotation": annotation, "axis": axis, "position": position}
                    )
        except Exception:
            pass
        try:
            current = annotation.GetNext()
        except Exception:
            break
    return rows


def arrange_dimensions(
    view_name: str | None = None,
    spacing_mm: float = DIMENSION_SPACING_MM,
    margin_mm: float = DIMENSION_MARGIN_MM,
) -> dict:
    """Re-space a view's linear dimensions into non-overlapping rows.

    DimXpert's AutoDimension stacks rows about 5-6 mm apart on this build,
    which collides at the default drawing text height. This pass keeps each
    dimension on its side of the view, preserves the original stacking order
    and enforces a fixed row spacing through IAnnotation.SetPosition. Rows
    that would run into a neighbouring view or the frame move to the opposite
    side of the view, or compress when neither side has room.
    """
    _, doc, _ = session.active_doc(("drawing",))
    if spacing_mm <= 0 or margin_mm < 0:
        raise InvalidParameterError(
            "spacing_mm must be positive and margin_mm must not be negative"
        )
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    if not _drawing(doc).ActivateView(resolved):
        raise ComCallError(f"SOLIDWORKS could not activate view {resolved!r}")
    outline = [float(value) for value in binding.value(view.GetOutline())]
    if len(outline) < 4:
        raise VerificationError("the view has no outline to arrange around", view=resolved)
    sheet_mm = _sheet_properties(_current_sheet(doc)).get("size_mm") or [0.0, 0.0]
    limits = None
    if sheet_mm[0] > 0 and sheet_mm[1] > 0:
        limits = _view_obstacle_limits(doc, view, outline, sheet_mm)
    rows = _view_linear_dimensions(view)
    plan = plan_dimension_arrangement(
        outline,
        rows,
        units.mm_to_m(spacing_mm),
        units.mm_to_m(margin_mm),
        limits_m=limits,
        min_spacing_m=units.mm_to_m(DIMENSION_MIN_SPACING_MM),
    )
    tolerance = units.mm_to_m(0.5)
    for entry in plan:
        row = rows[entry["index"]]
        x, y = entry["position"]
        before = row["position"]
        if abs(before[0] - x) < tolerance and abs(before[1] - y) < tolerance:
            continue
        row["annotation"].SetPosition(x, y, 0.0)
        after = [float(v) for v in binding.value(row["annotation"].GetPosition())]
        if abs(after[0] - x) > tolerance or abs(after[1] - y) > tolerance:
            raise VerificationError(
                "SOLIDWORKS did not move a dimension to the planned position",
                view=resolved,
                planned_mm=[round(units.m_to_mm(v), 2) for v in (x, y)],
                measured_mm=[round(units.m_to_mm(v), 2) for v in after],
            )
    groups: dict[str, int] = {}
    for entry in plan:
        groups[entry["side"]] = groups.get(entry["side"], 0) + 1
    flipped = sum(1 for entry in plan if entry["side"] != entry["original_side"])
    return {
        "data": {
            "view": resolved,
            "linear_dimensions": len(rows),
            "moved": len(plan),
            "spacing_mm": spacing_mm,
            "margin_mm": margin_mm,
            "groups": groups,
            "flipped": flipped,
            "limits_mm": (
                {key: round(units.m_to_mm(value), 2) for key, value in limits.items()}
                if limits
                else None
            ),
        },
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


# ---------------------------------------------------------------------------
# View entities (edges) for annotation attachment
# ---------------------------------------------------------------------------


def _edge_vertex_points(edge):
    """Return (start, end) vertex points in metres, or None."""
    try:
        start = binding.wrap(edge.GetStartVertex(), "IVertex")
        end = binding.wrap(edge.GetEndVertex(), "IVertex")
        start_point = [float(value) for value in binding.value(start.GetPoint()) or []]
        end_point = [float(value) for value in binding.value(end.GetPoint()) or []]
    except Exception:
        return None
    if len(start_point) >= 3 and len(end_point) >= 3:
        return start_point, end_point
    return None


def _view_edge_info(entity) -> dict:
    """Describe a view edge for annotation attachment.

    Measured on SW2026 SP0.0: a drawing view's circle/line parameters come
    back in **model** metres (a hole at model x=40 mm reads back as 40 mm),
    not sheet metres; the values are reported here in millimetres and are for
    identifying the feature, not for sheet placement. ``length_mm`` is the
    true 3D length and ``depth_mm`` the out-of-plane extent, because an edge
    along the view's depth axis projects to a point in x/y. Everything must
    be QueryInterfaced (IEntity -> IEdge -> ICurve, IVertex); late binding
    raises "Member not found".
    """
    info: dict = {"kind": "other"}
    try:
        edge = binding.wrap(entity, "IEdge")
        raw_curve = edge.GetCurve()
    except Exception:
        return info
    if raw_curve is None:
        return info
    try:
        curve = binding.wrap(raw_curve, "ICurve")
    except Exception:
        curve = raw_curve
    try:
        if bool(binding.value(curve.IsCircle)):
            info["kind"] = "circle"
            params = [float(value) for value in binding.value(curve.CircleParams) or []]
            if len(params) >= 7:
                info["center_mm"] = [
                    round(units.m_to_mm(params[0]), 3),
                    round(units.m_to_mm(params[1]), 3),
                ]
                info["radius_mm"] = round(units.m_to_mm(params[6]), 4)
            return info
        if bool(binding.value(curve.IsLine)):
            info["kind"] = "line"
            endpoints = None
            # ICurve.LineParams is point + direction, not two endpoints, so it
            # is not a length source; GetCurveParams2 or the edge vertices are.
            try:
                params = [
                    float(value)
                    for value in binding.value(curve.GetCurveParams2()) or []
                ]
                if len(params) >= 6:
                    endpoints = (params[0:3], params[3:6])
                    info["length_source"] = "curve_params"
            except Exception:
                endpoints = None
            if endpoints is None:
                endpoints = _edge_vertex_points(edge)
                if endpoints is not None:
                    info["length_source"] = "vertices"
            if endpoints is not None:
                start = [units.m_to_mm(value) for value in endpoints[0]]
                end = [units.m_to_mm(value) for value in endpoints[1]]
                info["start_mm"] = [round(value, 3) for value in start[:2]]
                info["end_mm"] = [round(value, 3) for value in end[:2]]
                if len(start) >= 3 and len(end) >= 3:
                    info["start3_mm"] = [round(value, 3) for value in start[:3]]
                    info["end3_mm"] = [round(value, 3) for value in end[:3]]
                # Measure the true 3D length: an edge along the view's depth
                # axis projects to a point in x/y (the side-view thickness
                # edges read as zero-length before this). ``depth_mm`` is the
                # out-of-plane extent, which is how those edges are addressed.
                info["length_mm"] = round(math.dist(start, end), 3)
                if len(start) >= 3 and abs(start[2] - end[2]) > 1e-9:
                    info["depth_mm"] = round(abs(start[2] - end[2]), 3)
    except Exception:
        pass
    return info


def _view_visible_edges(view) -> list:
    try:
        entities = view.GetVisibleEntities2(None, VIEW_ENTITY_EDGES)
    except Exception:
        entities = None
    return list(entities or [])


def list_view_edges(view_name: str | None = None) -> dict:
    """List a view's visible edges with indices for annotation attachment.

    Edge indices are stable for the current view state and are what
    ``insert_datum`` / ``insert_gtol`` / ``insert_surface_finish`` select
    before creating an annotation.
    """
    _, doc, _ = session.active_doc(("drawing",))
    active_sheet = _sheet_name(_current_sheet(doc))
    views = []
    for view in _views(doc, active_sheet):
        name = _view_name(view)
        if view_name is not None and name != view_name:
            continue
        edges = [
            {"index": index, **_view_edge_info(entity)}
            for index, entity in enumerate(_view_visible_edges(view))
        ]
        views.append({"name": name, "edges": edges, "count": len(edges)})
    return {
        "views": views,
        "total": sum(item["count"] for item in views),
        "sheet": active_sheet,
    }


# ---------------------------------------------------------------------------
# Dimensions and tolerances
# ---------------------------------------------------------------------------


def _view_annotations(view):
    """Yield wrapped IAnnotation objects for a view in stable order."""
    try:
        current = view.GetFirstAnnotation()
    except Exception:
        current = None
    guard = 0
    while current is not None and guard < 5000:
        guard += 1
        try:
            annotation = binding.wrap(current, "IAnnotation")
        except Exception:
            break
        yield annotation
        try:
            current = annotation.GetNext()
        except Exception:
            break


def _view_dimension_entries(view) -> list:
    """Return (annotation, display) for every dimension in a view."""
    entries = []
    for annotation in _view_annotations(view):
        try:
            if int(binding.value(annotation.GetType())) != 4:
                continue
            display = binding.wrap(
                annotation.GetSpecificAnnotation(), "IDisplayDimension"
            )
        except Exception:
            continue
        entries.append((annotation, display))
    return entries


def _dimension_text(display) -> str:
    """A dimension's readable override text (prefix + suffix), if any.

    Measured on SW2026 SP0.0: ``GetText(0)`` (``swDimensionTextAll``) always
    returns an empty string, even after ``SetText``; prefix (1) and suffix (2)
    are what actually read back.
    """
    try:
        return "".join(str(display.GetText(index) or "") for index in (1, 2))
    except Exception:
        return ""


def _dimension_entry_info(annotation, display) -> dict:
    info: dict = {"kind": "unknown"}
    try:
        code = int(binding.value(display.Type2))
        info["kind"] = DIMENSION_TYPES.get(code, "unknown")
        info["kind_code"] = code
    except Exception:
        pass
    text = _dimension_text(display)
    if text:
        info["text"] = text
    value = _dimension_value(display)
    if value is not None:
        info["value"] = round(value, 6)
    try:
        prefix = str(display.GetText(1) or "")
        suffix = str(display.GetText(2) or "")
        if prefix or suffix:
            info["prefix"] = prefix
            info["suffix"] = suffix
            if value is not None:
                info["reading"] = f"{prefix}{value}{suffix}"
    except Exception:
        pass
    try:
        info["visible"] = bool(binding.value(annotation.Visible))
    except Exception:
        pass
    try:
        info["show_dimension_value"] = bool(
            binding.value(display.ShowDimensionValue)
        )
    except Exception:
        pass
    try:
        position = list(binding.value(annotation.GetPosition()) or [])
        if len(position) >= 2:
            info["position_mm"] = [
                round(units.m_to_mm(value), 3) for value in position[:2]
            ]
    except Exception:
        pass
    tolerance = _tolerance_info(display)
    if tolerance:
        info["tolerance"] = tolerance
    try:
        if bool(binding.value(display.IsHoleCallout)):
            info["is_hole_callout"] = True
            variables = display.GetHoleCalloutVariables()
            if variables:
                info["hole_callout_variables"] = [str(item) for item in variables]
    except Exception:
        pass
    return info


def list_dimensions(view_name: str | None = None) -> dict:
    """List dimensions per model view with index, kind, value and tolerance.

    Indices are stable for the annotation order of a view and are what
    ``set_dimension_tolerance`` addresses; re-list after any geometry change.
    """
    _, doc, _ = session.active_doc(("drawing",))
    active_sheet = _sheet_name(_current_sheet(doc))
    views = []
    for view in _views(doc, active_sheet):
        name = _view_name(view)
        if view_name is not None and name != view_name:
            continue
        dimensions = [
            {"index": index, **_dimension_entry_info(annotation, display)}
            for index, (annotation, display) in enumerate(
                _view_dimension_entries(view)
            )
        ]
        views.append(
            {"name": name, "dimensions": dimensions, "count": len(dimensions)}
        )
    return {
        "views": views,
        "total": sum(item["count"] for item in views),
        "sheet": active_sheet,
    }


def plan_tolerance(
    tolerance: str,
    *,
    value_mm: float | None = None,
    minus_mm: float | None = None,
    plus_mm: float | None = None,
    lower_mm: float | None = None,
    upper_mm: float | None = None,
    hole_fit: str | None = None,
    shaft_fit: str | None = None,
) -> dict:
    """Translate a requested tolerance into IDimensionTolerance calls.

    Pure so the value semantics are unit-tested without SOLIDWORKS.
    ``symmetric`` takes one magnitude, ``bilateral`` takes positive minus/plus
    magnitudes (applied as signed deviations), ``limits`` takes the two
    absolute bounds, ``min``/``max`` take one bound, and the fit family takes
    ISO hole/shaft fit strings.
    """
    if tolerance not in TOLERANCE_TYPES:
        raise InvalidParameterError(
            f"unknown tolerance type {tolerance!r}",
            available=sorted(TOLERANCE_TYPES),
        )
    plan: dict = {"tolerance": tolerance, "type_code": TOLERANCE_TYPES[tolerance]}
    if tolerance in ("none", "basic"):
        return plan
    if tolerance == "symmetric":
        if value_mm is None:
            raise InvalidParameterError("symmetric tolerance needs value_mm")
        if float(value_mm) <= 0:
            raise InvalidParameterError("value_mm must be positive")
        plan["values"] = (float(value_mm), float(value_mm))
    elif tolerance == "bilateral":
        if minus_mm is None and plus_mm is None:
            raise InvalidParameterError(
                "bilateral tolerance needs minus_mm and/or plus_mm"
            )
        plan["values"] = (-abs(float(minus_mm or 0.0)), abs(float(plus_mm or 0.0)))
    elif tolerance == "limits":
        if lower_mm is None or upper_mm is None:
            raise InvalidParameterError(
                "limits tolerance needs lower_mm and upper_mm"
            )
        if float(lower_mm) >= float(upper_mm):
            raise InvalidParameterError("lower_mm must be below upper_mm")
        plan["values"] = (float(lower_mm), float(upper_mm))
    elif tolerance in ("min", "max"):
        if value_mm is None:
            raise InvalidParameterError(f"{tolerance} tolerance needs value_mm")
        plan["values"] = (float(value_mm), float(value_mm))
    else:  # the fit family
        if not hole_fit:
            raise InvalidParameterError("fit tolerance needs hole_fit")
        plan["fit"] = (str(hole_fit), str(shaft_fit or ""))
        if tolerance == "fit_with_tolerance":
            if minus_mm is None and plus_mm is None:
                raise InvalidParameterError(
                    "fit_with_tolerance needs minus_mm and/or plus_mm"
                )
            plan["values"] = (
                -abs(float(minus_mm or 0.0)),
                abs(float(plus_mm or 0.0)),
            )
    return plan


def set_dimension_tolerance(
    view_name: str | None = None,
    index: int | None = None,
    tolerance: str = "symmetric",
    value_mm: float | None = None,
    minus_mm: float | None = None,
    plus_mm: float | None = None,
    lower_mm: float | None = None,
    upper_mm: float | None = None,
    hole_fit: str | None = None,
    shaft_fit: str | None = None,
) -> dict:
    """Set one drawing dimension's tolerance and verify the read-back."""
    if index is None:
        raise InvalidParameterError(
            "index is required; call list_drawing_dimensions first"
        )
    plan = plan_tolerance(
        tolerance,
        value_mm=value_mm,
        minus_mm=minus_mm,
        plus_mm=plus_mm,
        lower_mm=lower_mm,
        upper_mm=upper_mm,
        hole_fit=hole_fit,
        shaft_fit=shaft_fit,
    )
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    entries = _view_dimension_entries(view)
    position = int(index)
    if position < 0 or position >= len(entries):
        raise SelectionError(
            f"dimension index {position} is out of range",
            view=resolved,
            available=len(entries),
            hint="Re-list with list_drawing_dimensions; indices follow the "
            "annotation order of the view.",
        )
    annotation, display = entries[position]
    dimension = binding.wrap(display.GetDimension2(0), "IDimension")
    tolerance_object = binding.wrap(
        binding.value(dimension.Tolerance), "IDimensionTolerance"
    )
    before = _tolerance_info(display)
    tolerance_object.Type = plan["type_code"]
    if "values" in plan:
        # SetValues takes metres (system units); the plan is millimetres.
        api_values = tuple(units.mm_to_m(float(value)) for value in plan["values"])
        if not bool(tolerance_object.SetValues(*api_values)):
            raise VerificationError(
                "SOLIDWORKS refused the tolerance values",
                values=list(plan["values"]),
                dimension=_dimension_text(display),
            )
    if "fit" in plan:
        if not bool(tolerance_object.SetFitValues(*plan["fit"])):
            raise VerificationError(
                "SOLIDWORKS refused the fit values",
                fit=list(plan["fit"]),
                dimension=_dimension_text(display),
            )
    after = _tolerance_info(display)
    if after is None or after.get("type") != tolerance:
        raise VerificationError(
            "SOLIDWORKS did not retain the requested tolerance type",
            requested=tolerance,
            measured=after,
        )
    values = plan.get("values")
    if values is not None:
        measured = (after.get("min"), after.get("max"))
        if (
            measured[0] is None
            or measured[1] is None
            or abs(measured[0] - values[0]) > 1e-6
            or abs(measured[1] - values[1]) > 1e-6
        ):
            raise VerificationError(
                "SOLIDWORKS did not retain the requested tolerance values",
                requested=list(values),
                measured=list(measured),
            )
    fit = plan.get("fit")
    if fit is not None and (
        after.get("hole_fit"), after.get("shaft_fit")
    ) != tuple(fit):
        raise VerificationError(
            "SOLIDWORKS did not retain the requested fit",
            requested=list(fit),
            measured=[after.get("hole_fit"), after.get("shaft_fit")],
        )
    return {
        "data": {
            "view": resolved,
            "index": position,
            "text": _dimension_text(display),
            "value": _dimension_value(display),
            "tolerance_before": before,
            "tolerance": after,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "dimensions": list_dimensions(resolved),
        },
    }


def insert_general_tolerance_table(
    x: int | None = None,
    y: int | None = None,
) -> dict:
    """Insert the general tolerance table (ISO 2768-mK) where supported.

    ``InsertGeneralToleranceTableAnnotation(TemplateName, X, Y)`` takes long
    coordinates; the default template is used. Measured on SW2026 SP0.0 the
    annotation only exists for parts/assemblies, so a drawing can legitimately
    refuse it and callers should fall back to a general tolerance note.
    """
    _, doc, _ = session.active_doc(("drawing",))
    _drawing(doc)
    raw = _extension(doc).InsertGeneralToleranceTableAnnotation(
        "", int(x or 0), int(y or 0)
    )
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not insert a general tolerance table",
            hint="Measured on SW2026 SP0.0: this annotation is available for "
            "parts/assemblies through the API; on a drawing add a "
            "'General tolerances ISO 2768-mK' note instead.",
        )
    table = binding.wrap(raw, "IGeneralToleranceTableAnnotation")
    feature_name = None
    try:
        feature = binding.wrap(
            table.GeneralToleranceTableFeature(), "IFeature"
        )
        feature_name = str(binding.value(feature.Name) or "")
    except Exception:
        pass
    return {
        "data": {
            "table": "general_tolerance",
            "feature": feature_name,
            "x": int(x or 0),
            "y": int(y or 0),
        },
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


# ---------------------------------------------------------------------------
# Revision table
# ---------------------------------------------------------------------------

# Measured on SW2026 SP0.0: UseAnchorPoint=True with anchor type 1 places the
# stock revision table (other anchor types return None).
REVISION_TABLE_ANCHOR = 1


def _table_annotation(doc, table_type: int = 14):
    """The sheet's table annotation, wrapped as ``IAnnotation``.

    Tables need the annotation interface for ``GetPosition``/``SetPosition``:
    the dispatch from ``ISheet.RevisionTable`` wraps back to
    ``ITableAnnotation``/``IRevisionTableAnnotation`` and has no position
    members, while the annotation from the view walk does.
    """
    for view in _views(doc):
        for annotation in _view_annotations(view):
            try:
                if int(annotation.GetType()) == table_type:
                    return annotation
            except Exception:
                continue
    return None


FRAME_INSET_MM = 10.0


def _fit_revision_table(doc) -> dict:
    """Place the revision table inside the frame and report its box.

    Measured on SW2026 SP0.0: the anchored table pins its bottom-left corner
    to the frame's inner top-right corner and grows **upward** as revision
    rows are added, and ``SetPosition`` is ignored while
    ``ITableAnnotation.Anchored`` is true. The stock ISO/ANSI frames inset
    the top and right borders by 10 mm; the table is placed 2 mm below the
    top border, right-aligned to the frame.
    """
    annotation = _table_annotation(doc)
    if annotation is None:
        raise SelectionError("could not find the revision table")
    table = binding.wrap(annotation.GetSpecificAnnotation(), "ITableAnnotation")
    columns = int(binding.value(table.ColumnCount))
    rows = int(binding.value(table.RowCount))
    width = sum(
        float(binding.value(table.GetColumnWidth(index))) for index in range(columns)
    )
    height = sum(
        float(binding.value(table.GetRowHeight(index))) for index in range(rows)
    )
    size = _sheet_properties(_current_sheet(doc)).get("size_mm") or [420.0, 297.0]
    corner_x = units.mm_to_m(float(size[0]) - FRAME_INSET_MM)
    corner_y = units.mm_to_m(float(size[1]) - FRAME_INSET_MM)
    target_x = corner_x - width
    target_y = corner_y - height - units.mm_to_m(2.0)
    table.Anchored = False
    annotation.SetPosition(target_x, target_y, 0.0)
    measured = [float(value) for value in binding.value(annotation.GetPosition())[:2]]
    tolerance = units.mm_to_m(0.1)
    if (
        abs(measured[0] - target_x) > tolerance
        or abs(measured[1] - target_y) > tolerance
    ):
        raise VerificationError(
            "could not position the revision table inside the frame",
            expected_mm=[
                round(units.m_to_mm(target_x), 2),
                round(units.m_to_mm(target_y), 2),
            ],
            measured_mm=[round(units.m_to_mm(value), 2) for value in measured[:2]],
        )
    return {
        "position_mm": [round(units.m_to_mm(value), 2) for value in measured[:2]],
        "size_mm": {
            "width": round(units.m_to_mm(width), 2),
            "height": round(units.m_to_mm(height), 2),
        },
        "inside_frame": (
            measured[0] + width <= corner_x + tolerance
            and measured[1] + height <= corner_y + tolerance
        ),
    }


def insert_revision_table(
    anchor_type: int = REVISION_TABLE_ANCHOR,
    template: str = "",
) -> dict:
    """Insert the sheet's revision table and read its columns back."""
    _, doc, _ = session.active_doc(("drawing",))
    _drawing(doc)
    sheet = _current_sheet(doc)
    raw = sheet.InsertRevisionTable2(
        True, 0.0, 0.0, int(anchor_type), str(template), 0, True
    )
    if raw is None:
        try:
            raw = binding.value(sheet.RevisionTable)
        except Exception:
            raw = None
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not insert a revision table",
            hint="Measured on SW2026 SP0.0: UseAnchorPoint=True with "
            "AnchorType=1 works on the stock ISO/ANSI frames.",
        )
    table = binding.wrap(raw, "IRevisionTableAnnotation")
    data: dict = {
        "current_revision": str(binding.value(table.CurrentRevision) or "")
    }
    try:
        base = binding.wrap(raw, "ITableAnnotation")
        columns = int(binding.value(base.ColumnCount))
        rows = int(binding.value(base.RowCount))
        data["rows"] = rows
        data["columns"] = columns
        data["column_titles"] = [
            str(base.GetColumnTitle(index) or "") for index in range(columns)
        ]
        # Measured on SW2026 SP0.0: the anchored table pins its bottom-left
        # corner to the frame's top-right corner and grows up/right into the
        # margin (and SetPosition is ignored while Anchored is true).
        # Unanchor it and tuck it inside the frame.
        try:
            data.update(_fit_revision_table(doc))
        except VerificationError:
            raise
        except Exception:
            data["inside_frame"] = False
            data["frame_warning"] = (
                "the table is anchored at the frame corner and may cross the "
                "border; reposition it manually"
            )
    except VerificationError:
        raise
    except Exception:
        pass
    return {"data": data, "evidence": {"rebuild": inspect.rebuild(doc)}}


def add_revision(
    revision: str,
    description: str | None = None,
    date: str | None = None,
    zone: str | None = None,
    approved: str | None = None,
) -> dict:
    """Add a revision row and verify the table's current revision."""
    if not str(revision).strip():
        raise InvalidParameterError("revision must not be empty")
    _, doc, _ = session.active_doc(("drawing",))
    _drawing(doc)
    sheet = _current_sheet(doc)
    raw = binding.value(sheet.RevisionTable)
    if raw is None:
        raise SelectionError(
            "the active sheet has no revision table",
            hint="Call drawing_insert_revision_table first.",
        )
    table = binding.wrap(raw, "IRevisionTableAnnotation")
    before = str(binding.value(table.CurrentRevision) or "")
    revision_id = table.AddRevision(str(revision))
    after = str(binding.value(table.CurrentRevision) or "")
    if after != str(revision):
        raise VerificationError(
            "SOLIDWORKS did not retain the revision",
            expected=str(revision),
            measured=after,
        )
    cells: dict = {}
    wanted = {
        "DESCRIPTION": description,
        "DATE": date,
        "ZONE": zone,
        "APPROVED": approved,
    }
    if any(value is not None for value in wanted.values()):
        try:
            base = binding.wrap(raw, "ITableAnnotation")
            columns = int(binding.value(base.ColumnCount))
            titles = {
                str(base.GetColumnTitle(index) or "").strip().upper(): index
                for index in range(columns)
            }
            row = int(table.GetRowNumberForId(int(revision_id)))
            for title, value in wanted.items():
                if value is None or title not in titles:
                    continue
                # ITableAnnotation.Text is the generated getter; the putter is
                # SetText(Row, Column, Value).
                base.SetText(row, titles[title], str(value))
                cells[title] = str(value)
        except Exception as exc:
            cells.setdefault("_error", str(exc))
    # Adding a row grows the table upward from its bottom-left corner, so
    # re-fit it inside the frame on every revision (measured 2026-09-27).
    placement: dict | None = None
    try:
        placement = _fit_revision_table(doc)
    except Exception:
        placement = None
    data: dict = {
        "revision": after,
        "previous": before,
        "revision_id": int(revision_id),
        "cells": cells,
    }
    if placement is not None:
        data["placement"] = placement
    return {
        "data": data,
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


# ---------------------------------------------------------------------------
# Datum tags, geometric tolerances, surface finish
# ---------------------------------------------------------------------------


def _view_annotations_of_type(view, type_code: int) -> list:
    found = []
    for annotation in _view_annotations(view):
        try:
            if int(binding.value(annotation.GetType())) == type_code:
                found.append(annotation)
        except Exception:
            continue
    return found


def insert_datum(
    view_name: str | None = None,
    edge_index: int | None = None,
    label: str = "A",
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> dict:
    """Attach a datum tag to a view edge and verify the label read-back."""
    if edge_index is None:
        raise InvalidParameterError(
            "edge_index is required; call list_drawing_view_edges first"
        )
    if not str(label).strip():
        raise InvalidParameterError("label must not be empty")
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    entities = _view_visible_edges(view)
    position = int(edge_index)
    if position < 0 or position >= len(entities):
        raise SelectionError(
            f"edge index {position} is out of range",
            view=resolved,
            available=len(entities),
            hint="Re-list with list_drawing_view_edges.",
        )
    session.clear_selection(doc)
    if not view.SelectEntity(entities[position], False):
        raise SelectionError(
            f"could not select edge {position} in view {resolved!r}"
        )
    before = len(_view_annotations_of_type(view, 2))
    drawing.InsertDatumTag()
    after = _view_annotations_of_type(view, 2)
    if len(after) <= before:
        raise VerificationError(
            "SOLIDWORKS did not create a datum tag", view=resolved
        )
    annotation = after[-1]
    tag = binding.wrap(annotation.GetSpecificAnnotation(), "IDatumTag")
    if not bool(tag.SetLabel(str(label))):
        raise VerificationError(
            "SOLIDWORKS refused the datum label", label=str(label)
        )
    measured = str(binding.value(tag.GetLabel) or "")
    if measured != str(label):
        raise VerificationError(
            "SOLIDWORKS did not retain the datum label",
            expected=str(label),
            measured=measured,
        )
    if x_mm is not None and y_mm is not None:
        annotation.SetPosition(
            units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0
        )
    session.clear_selection(doc)
    measured_position = [
        round(units.m_to_mm(value), 2)
        for value in binding.value(annotation.GetPosition())[:2]
    ]
    text_position = _datum_text_position(tag)
    neighbors = _nearby_datum_tags(doc, text_position) if text_position else []
    data: dict = {
        "view": resolved,
        "edge_index": position,
        "label": measured,
        "position_mm": measured_position,
        "placement_note": (
            "the along-edge coordinate snaps to the edge's start vertex on "
            "this build; the free coordinate separates datum tags"
        ),
    }
    if text_position:
        data["text_position_mm"] = text_position
    if neighbors:
        data["nearby_datum_tags"] = neighbors
    return {
        "data": data,
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "annotations": list_annotations(resolved),
        },
    }


MIN_DATUM_GAP_MM = 10.0


def _datum_text_position(tag) -> list[float] | None:
    """The datum tag's letter-box position in mm (its display position)."""
    try:
        raw = binding.value(tag.GetTextPositionAtIndex(0))
        if raw and len(raw) >= 2:
            return [round(units.m_to_mm(float(value)), 2) for value in raw[:2]]
    except Exception:
        pass
    return None


def _nearby_datum_tags(doc, own_position_mm: list[float]) -> list[dict]:
    """Other datum tags whose letter boxes sit closer than MIN_DATUM_GAP_MM."""
    neighbors = []
    for view in _views(doc):
        for annotation in _view_annotations(view):
            try:
                if int(annotation.GetType()) != 2:
                    continue
                tag = binding.wrap(annotation.GetSpecificAnnotation(), "IDatumTag")
                label = str(binding.value(tag.GetLabel) or "")
                position = _datum_text_position(tag)
            except Exception:
                continue
            if position is None:
                continue
            distance = math.dist(position, own_position_mm)
            if distance <= 0.01:  # the tag just inserted
                continue
            if distance < MIN_DATUM_GAP_MM:
                neighbors.append(
                    {
                        "label": label,
                        "distance_mm": round(distance, 2),
                        "position_mm": position,
                    }
                )
    return neighbors


def insert_gtol(
    view_name: str | None = None,
    edge_index: int | None = None,
    symbol: str = "position",
    tolerance: str = "0.2",
    tolerance2: str | None = None,
    datums: list[str] | None = None,
    diameter: bool = False,
    material_condition: str = "none",
    datum_material_conditions: list[str] | None = None,
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> dict:
    """Insert a single-frame geometric tolerance attached to a view edge."""
    if edge_index is None:
        raise InvalidParameterError(
            "edge_index is required; call list_drawing_view_edges first"
        )
    if symbol not in GTOL_SYMBOLS:
        raise InvalidParameterError(
            f"unknown geometric tolerance symbol {symbol!r}",
            available=sorted(GTOL_SYMBOLS),
        )
    if material_condition not in MATERIAL_CONDITIONS:
        raise InvalidParameterError(
            f"unknown material condition {material_condition!r}",
            available=sorted(MATERIAL_CONDITIONS),
        )
    if not str(tolerance).strip():
        raise InvalidParameterError("tolerance text must not be empty")
    datum_refs = [str(item) for item in (datums or [])]
    if len(datum_refs) > 3:
        raise InvalidParameterError("at most three datum references are supported")
    datum_mcs = [str(item) for item in (datum_material_conditions or [])]
    if len(datum_mcs) > 3:
        raise InvalidParameterError(
            "at most three datum material conditions are supported"
        )
    for condition in datum_mcs:
        if condition not in MATERIAL_CONDITIONS:
            raise InvalidParameterError(
                f"unknown datum material condition {condition!r}",
                available=sorted(MATERIAL_CONDITIONS),
            )
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    entities = _view_visible_edges(view)
    position = int(edge_index)
    if position < 0 or position >= len(entities):
        raise SelectionError(
            f"edge index {position} is out of range",
            view=resolved,
            available=len(entities),
            hint="Re-list with list_drawing_view_edges.",
        )
    session.clear_selection(doc)
    if not view.SelectEntity(entities[position], False):
        raise SelectionError(
            f"could not select edge {position} in view {resolved!r}"
        )
    raw = doc.InsertGtol()
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not create the geometric tolerance", view=resolved
        )
    gtol = binding.wrap(raw, "IGtol")
    values = (
        str(tolerance),
        str(tolerance2 or ""),
        datum_refs[0] if len(datum_refs) > 0 else "",
        datum_refs[1] if len(datum_refs) > 1 else "",
        datum_refs[2] if len(datum_refs) > 2 else "",
    )
    if not bool(gtol.SetFrameValues2(1, *values)):
        raise VerificationError(
            "SOLIDWORKS refused the geometric tolerance values",
            values=list(values),
        )
    symbols = (
        GTOL_SYMBOLS[symbol],
        1 if diameter else 0,
        MATERIAL_CONDITIONS[material_condition],
        0,
        0,
        MATERIAL_CONDITIONS[datum_mcs[0]] if len(datum_mcs) > 0 else 0,
        MATERIAL_CONDITIONS[datum_mcs[1]] if len(datum_mcs) > 1 else 0,
        MATERIAL_CONDITIONS[datum_mcs[2]] if len(datum_mcs) > 2 else 0,
    )
    # SetFrameSymbols returns void on this build but still applies.
    gtol.SetFrameSymbols(1, *symbols)
    measured_values = [
        str(item) for item in binding.value(gtol.GetFrameValues(1)) or []
    ]
    if measured_values != list(values):
        raise VerificationError(
            "SOLIDWORKS did not retain the geometric tolerance frame values",
            expected=list(values),
            measured=measured_values,
        )
    measured_symbols = [
        int(item) for item in binding.value(gtol.GetFrameSymbols(1)) or []
    ]
    if not measured_symbols or measured_symbols[0] != GTOL_SYMBOLS[symbol]:
        raise VerificationError(
            "SOLIDWORKS did not retain the geometric tolerance symbol",
            expected=GTOL_SYMBOLS[symbol],
            measured=measured_symbols,
        )
    if x_mm is not None and y_mm is not None:
        session.clear_selection(doc)
        annotation = binding.wrap(gtol.GetAnnotation(), "IAnnotation")
        annotation.SetPosition(units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0)
    session.clear_selection(doc)
    return {
        "data": {
            "view": resolved,
            "edge_index": position,
            "symbol": symbol,
            "tolerance": str(tolerance),
            "datums": datum_refs,
            "frame_values": measured_values,
            "frame_symbols": measured_symbols,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "annotations": list_annotations(resolved),
        },
    }


def insert_surface_finish(
    view_name: str | None = None,
    edge_index: int | None = None,
    roughness: str = "1.6",
    symbol: str = "basic",
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> dict:
    """Insert a surface finish symbol and verify its roughness text.

    Measured on SW2026 SP0.0: the visible roughness value comes from the
    ``MaxRoughness`` parameter and reads back through ``ISFSymbol.GetText(5)``.
    ``MachAllowance`` stores a string at ``GetText(1)`` but it is **not drawn**
    (the earlier callout rendered with no value); the remaining parameters map
    to text indices 4 (``OtherVals``), 6 (``MinRoughness``) and 3 (sample
    length) with ``GetTextCount()`` still reporting 0.
    """
    if symbol not in SURFACE_FINISH_SYMBOLS:
        raise InvalidParameterError(
            f"unknown surface finish symbol {symbol!r}",
            available=sorted(SURFACE_FINISH_SYMBOLS),
        )
    if not str(roughness).strip():
        raise InvalidParameterError("roughness must not be empty")
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    if edge_index is not None:
        entities = _view_visible_edges(view)
        position = int(edge_index)
        if position < 0 or position >= len(entities):
            raise SelectionError(
                f"edge index {position} is out of range",
                view=resolved,
                available=len(entities),
                hint="Re-list with list_drawing_view_edges.",
            )
        session.clear_selection(doc)
        if not view.SelectEntity(entities[position], False):
            raise SelectionError(
                f"could not select edge {position} in view {resolved!r}"
            )
    view_position = [float(value) for value in binding.value(view.Position) or []]
    while len(view_position) < 3:
        view_position.append(0.0)
    location_x = units.mm_to_m(x_mm) if x_mm is not None else view_position[0]
    location_y = units.mm_to_m(y_mm) if y_mm is not None else view_position[1]
    raw = _extension(doc).InsertSurfaceFinishSymbol3(
        SURFACE_FINISH_SYMBOLS[symbol],
        1,
        location_x,
        location_y,
        view_position[2],
        0,
        0,
        "",  # MachAllowance: stored but not displayed
        "",
        "",
        "",
        str(roughness),  # MaxRoughness: the displayed value (GetText(5))
        "",
        "",
    )
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not create the surface finish symbol", view=resolved
        )
    sf = binding.wrap(raw, "ISFSymbol")
    texts = [str(sf.GetText(index) or "") for index in range(7)]
    measured = next((text for text in texts if text), "")
    if str(roughness) not in measured:
        raise VerificationError(
            "SOLIDWORKS did not retain the surface roughness value",
            expected=str(roughness),
            measured=texts,
        )
    session.clear_selection(doc)
    return {
        "data": {
            "view": resolved,
            "edge_index": edge_index,
            "roughness": measured,
            "symbol": symbol,
            "texts": texts,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "annotations": list_annotations(resolved),
        },
    }


# ---------------------------------------------------------------------------
# Assembly drawings: BOM and balloons
# ---------------------------------------------------------------------------


def _view_referenced_configuration(view) -> str:
    """Resolve the configuration a BOM table must reference.

    ``IView.ReferencedConfiguration`` is PROPPUT-only on this build, so read
    the referenced model document's active configuration instead.
    """
    try:
        model_path = str(binding.value(view.GetReferencedModelName) or "")
    except Exception:
        model_path = ""
    for raw_doc in session.app().GetDocuments() or []:
        try:
            candidate = session.wrap_doc(raw_doc)
            path = str(binding.value(candidate.GetPathName) or "")
        except Exception:
            continue
        if model_path and path.lower() != model_path.lower():
            continue
        try:
            manager = candidate.ConfigurationManager
            active = binding.wrap(manager.ActiveConfiguration, "IConfiguration")
            name = str(binding.value(active.Name) or "")
            if name:
                return name
        except Exception:
            pass
        try:
            names = [
                str(name)
                for name in binding.value(candidate.GetConfigurationNames()) or []
            ]
            if names:
                return names[0]
        except Exception:
            pass
    return ""


def _select_drawing_view(doc, resolved: str) -> None:
    session.clear_selection(doc)
    if not _extension(doc).SelectByID2(
        resolved, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0
    ):
        raise SelectionError(
            f"could not select drawing view {resolved!r}",
            hint="Use a model view name from list_drawing_views.",
        )


def insert_bom_table(
    view_name: str | None = None,
    bom_type: str = "top_level_only",
    configuration: str | None = None,
) -> dict:
    """Insert a BOM table for an assembly drawing view and read it back.

    Measured on SW2026 SP0.0: the table needs UseAnchorPoint=True with
    AnchorType=1 and the view's **referenced configuration**; an empty
    configuration produces a header-only table.
    """
    if bom_type not in BOM_TYPES:
        raise InvalidParameterError(
            f"unknown BOM type {bom_type!r}", available=sorted(BOM_TYPES)
        )
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    _select_drawing_view(doc, resolved)
    config = str(configuration) if configuration is not None else ""
    if not config:
        config = _view_referenced_configuration(view)
    raw = view.InsertBomTable5(
        True,
        0.0,
        0.0,
        1,
        BOM_TYPES[bom_type],
        config,
        "",
        False,
        0,
        False,
        False,
    )
    session.clear_selection(doc)
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not insert a BOM table",
            hint="Measured on SW2026 SP0.0: UseAnchorPoint=True with "
            "AnchorType=1 works; the view must reference an assembly.",
        )
    table = binding.wrap(raw, "ITableAnnotation")
    rows = int(binding.value(table.RowCount))
    columns = int(binding.value(table.ColumnCount))
    if rows <= 1:
        raise VerificationError(
            "SOLIDWORKS created a header-only BOM table",
            view=resolved,
            configuration=config,
            hint="Pass the configuration the view references (an empty or "
            "mismatched configuration produces no items).",
        )
    titles = [str(table.GetColumnTitle(index) or "") for index in range(columns)]
    items = [
        [str(table.Text(row, column) or "") for column in range(columns)]
        for row in range(1, min(rows, 500))
    ]
    return {
        "data": {
            "view": resolved,
            "bom_type": bom_type,
            "configuration": config,
            "rows": rows,
            "columns": columns,
            "column_titles": titles,
            "items": items,
        },
        "evidence": {"rebuild": inspect.rebuild(doc)},
    }


def insert_balloons(
    view_name: str | None = None,
    style: str = "circular",
    fit: str = "3_chars",
    layout: str = "circle",
    item_number_start: int = 1,
) -> dict:
    """Auto-balloon an assembly drawing view and read the balloons back."""
    if style not in BALLOON_STYLES:
        raise InvalidParameterError(
            f"unknown balloon style {style!r}", available=sorted(BALLOON_STYLES)
        )
    if fit not in BALLOON_FITS:
        raise InvalidParameterError(
            f"unknown balloon fit {fit!r}", available=sorted(BALLOON_FITS)
        )
    if layout not in BALLOON_LAYOUTS:
        raise InvalidParameterError(
            f"unknown balloon layout {layout!r}",
            available=sorted(BALLOON_LAYOUTS),
        )
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    _select_drawing_view(doc, resolved)
    options = drawing.CreateAutoBalloonOptions()
    if options is None:
        raise ComCallError("SOLIDWORKS did not provide auto-balloon options")
    options.Style = BALLOON_STYLES[style]
    options.Size = BALLOON_FITS[fit]
    options.Layout = BALLOON_LAYOUTS[layout]
    options.ItemNumberStart = int(item_number_start)
    options.ItemOrder = 1
    options.InsertMagneticLine = False
    result = drawing.AutoBalloon5(options)
    session.clear_selection(doc)
    if result is None:
        raise ComCallError(
            "SOLIDWORKS did not insert balloons",
            hint="Balloons need an assembly drawing view with component "
            "geometry; add the BOM table first so item numbers exist.",
        )
    balloons = []
    for annotation in _view_annotations_of_type(view, 6):
        try:
            note = binding.wrap(annotation.GetSpecificAnnotation(), "INote")
            if bool(binding.value(note.IsBomBalloon)):
                balloons.append(str(binding.value(note.GetText) or ""))
        except Exception:
            continue
    if not balloons:
        raise VerificationError(
            "no balloon annotations were found after auto-ballooning",
            view=resolved,
        )
    return {
        "data": {
            "view": resolved,
            "style": style,
            "fit": fit,
            "layout": layout,
            "count": len(balloons),
            "balloons": balloons,
        },
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "annotations": list_annotations(resolved),
        },
    }


# ---------------------------------------------------------------------------
# Hole callouts
# ---------------------------------------------------------------------------


def insert_hole_callout(
    view_name: str | None = None,
    edge_index: int | None = None,
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> dict:
    """Add a hole callout for a hole that carries callout data.

    Measured on SW2026 SP0.0: ``AddHoleCallout`` and ``AddHoleCallout2``
    return nothing for ``SimpleHole2`` holes, sketch/extruded-cut holes and
    the practice-part holes tested here; the callout data comes from a Hole
    Wizard feature. The tool reports that refusal with an actionable hint
    instead of pretending a callout was placed.
    """
    _, doc, _ = session.active_doc(("drawing",))
    view = _model_view(doc, view_name)
    resolved = _view_name(view)
    drawing = _drawing(doc)
    if not drawing.ActivateView(resolved):
        raise ComCallError(f"could not activate view {resolved!r}")
    selected_circle = False
    if edge_index is not None:
        entities = _view_visible_edges(view)
        position = int(edge_index)
        if position < 0 or position >= len(entities):
            raise SelectionError(
                f"edge index {position} is out of range",
                view=resolved,
                available=len(entities),
                hint="Re-list with list_drawing_view_edges.",
            )
        info = _view_edge_info(entities[position])
        if info.get("kind") != "circle":
            raise SelectionError(
                "hole callouts attach to circular edges",
                edge_index=position,
                kind=info.get("kind"),
            )
        session.clear_selection(doc)
        if not view.SelectEntity(entities[position], False):
            raise SelectionError(
                f"could not select edge {position} in view {resolved!r}"
            )
        selected_circle = True
    raw = drawing.AddHoleCallout()
    if raw is None and selected_circle and x_mm is not None and y_mm is not None:
        raw = drawing.AddHoleCallout2(
            units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0
        )
    session.clear_selection(doc)
    if raw is None:
        raise ComCallError(
            "SOLIDWORKS did not create a hole callout",
            view=resolved,
            hint="Measured on this build: callouts are only produced for "
            "holes with callout data (create the hole with the Hole Wizard); "
            "SimpleHole2 and sketch/extruded-cut holes refuse.",
        )
    display = binding.wrap(raw, "IDisplayDimension")
    info: dict = {"view": resolved}
    try:
        info["is_hole_callout"] = bool(binding.value(display.IsHoleCallout))
        info["variables"] = [
            str(item) for item in display.GetHoleCalloutVariables() or []
        ]
    except Exception:
        pass
    info["text"] = str(display.GetText(0) or "")
    return {
        "data": info,
        "evidence": {
            "rebuild": inspect.rebuild(doc),
            "annotations": list_annotations(resolved),
        },
    }
