"""Sketch creation and 2D geometry.

All coordinates are millimetres in the sketch coordinate system (the sketch
plane maps XY to the model plane; Z is ignored).
"""
from __future__ import annotations

from ..com import binding, units
from ..errors import ComCallError, InvalidParameterError, SelectionError
from . import inspect, session

SEGMENT_TYPES = {
    0: "line",
    1: "circle",
    2: "arc",
    3: "ellipse",
    4: "spline",
    5: "point",
    6: "parabola",
    7: "text",
}


def _sketch_manager(doc):
    return doc.SketchManager


def _active_sketch(doc):
    sketch = _sketch_manager(doc).ActiveSketch
    if sketch is None:
        raise SelectionError(
            "no active sketch",
            hint="Call create_sketch first, then draw geometry, then exit_sketch.",
        )
    return sketch


def _wrap_segments(raw) -> list:
    return [binding.wrap(segment, "ISketchSegment") for segment in raw or []]


def _mm(value: float) -> float:
    return units.mm_to_m(float(value))


def create_sketch(plane: str | None = None, face_index: int | None = None) -> dict:
    _, doc, _ = session.active_doc(("part",))
    if face_index is not None:
        inspect.select_faces(doc, [face_index])
        target: dict = {"face_index": face_index}
    else:
        target = {"plane": session.select_plane(doc, plane)}
    _sketch_manager(doc).InsertSketch(True)
    if _sketch_manager(doc).ActiveSketch is None:
        raise ComCallError("sketch mode did not start")
    target["active"] = True
    return target


def exit_sketch() -> dict:
    _, doc, _ = session.active_doc(("part",))
    if _sketch_manager(doc).ActiveSketch is None:
        raise SelectionError("no active sketch to exit")
    _sketch_manager(doc).InsertSketch(True)
    return {"active_sketch": _sketch_manager(doc).ActiveSketch is not None}


def _require_sketch(func):
    def wrapper(*args, **kwargs):
        _, doc, _ = session.active_doc(("part",))
        _active_sketch(doc)
        return func(doc, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


@_require_sketch
def rectangle(doc, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float,
              centered: bool = False) -> dict:
    manager = _sketch_manager(doc)
    create = manager.CreateCenterRectangle if centered else manager.CreateCornerRectangle
    raw = create(_mm(x1_mm), _mm(y1_mm), 0.0, _mm(x2_mm), _mm(y2_mm), 0.0)
    return {"segments_created": len(raw or [])}


@_require_sketch
def circle(doc, center_x_mm: float, center_y_mm: float, radius_mm: float) -> dict:
    if radius_mm <= 0:
        raise InvalidParameterError("radius_mm must be positive")
    segment = _sketch_manager(doc).CreateCircleByRadius(
        _mm(center_x_mm), _mm(center_y_mm), 0.0, _mm(radius_mm)
    )
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def line(doc, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float,
         construction: bool = False) -> dict:
    manager = _sketch_manager(doc)
    if construction:
        segment = manager.CreateCenterLine(
            _mm(x1_mm), _mm(y1_mm), 0.0, _mm(x2_mm), _mm(y2_mm), 0.0
        )
    else:
        segment = manager.CreateLine(
            _mm(x1_mm), _mm(y1_mm), 0.0, _mm(x2_mm), _mm(y2_mm), 0.0
        )
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def polygon(doc, center_x_mm: float, center_y_mm: float, radius_mm: float,
            sides: int, inscribed: bool = True) -> dict:
    if sides < 3:
        raise InvalidParameterError("sides must be >= 3")
    raw = _sketch_manager(doc).CreatePolygon(
        _mm(center_x_mm),
        _mm(center_y_mm),
        0.0,
        _mm(center_x_mm + radius_mm),
        _mm(center_y_mm),
        0.0,
        sides,
        bool(inscribed),
    )
    return {"segments_created": len(raw or [])}


@_require_sketch
def spline(doc, points_mm: list[list[float]]) -> dict:
    if len(points_mm) < 2:
        raise InvalidParameterError("a spline needs at least 2 points")
    flat = []
    for point in points_mm:
        flat.extend([_mm(point[0]), _mm(point[1]), 0.0])
    raw = _sketch_manager(doc).CreateSpline(flat)
    return {"segments_created": 1 if raw else 0}


@_require_sketch
def sketch_fillet(doc, radius_mm: float) -> dict:
    segment = _sketch_manager(doc).CreateFillet(_mm(radius_mm), 0)
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def sketch_chamfer(doc, distance_mm: float, angle_deg: float = 45.0) -> dict:
    segment = _sketch_manager(doc).CreateChamfer(
        0, _mm(distance_mm), units.deg_to_rad(angle_deg)
    )
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def offset(doc, offset_mm: float, both_directions: bool = False,
           chain: bool = True, make_construction: bool = False) -> dict:
    ok = _sketch_manager(doc).SketchOffset2(
        _mm(offset_mm),
        bool(both_directions),
        bool(chain),
        0,
        1 if make_construction else 0,
        False,
    )
    return {"ok": bool(ok)}


@_require_sketch
def convert_entities(doc) -> dict:
    _sketch_manager(doc).ConvertEntities()
    return {"ok": True}


def _segment_point(segment) -> tuple[float, float, float]:
    for getter in ("GetStartPoint2", "GetEndPoint2"):
        try:
            point = binding.wrap(getattr(segment, getter)(), "ISketchPoint")
            return (
                float(binding.value(point.X)),
                float(binding.value(point.Y)),
                float(binding.value(point.Z)),
            )
        except Exception:
            continue
    try:
        curve = segment.GetCurve()
        if curve is not None:
            evaluated = binding.value(curve.Evaluate2(0.5, 0))
            if evaluated and len(evaluated) >= 3:
                return (float(evaluated[0]), float(evaluated[1]), float(evaluated[2]))
    except Exception:
        pass
    raise SelectionError("could not locate a point on the sketch segment")


def list_sketch_segments() -> dict:
    _, doc, _ = session.active_doc(("part",))
    sketch = _active_sketch(doc)
    segments = _wrap_segments(sketch.GetSketchSegments())
    infos = []
    for index, segment in enumerate(segments):
        info: dict = {"index": index}
        try:
            type_id = int(segment.GetType())
            info["type"] = SEGMENT_TYPES.get(type_id, str(type_id))
        except Exception:
            pass
        try:
            info["construction"] = bool(binding.value(segment.ConstructionGeometry))
        except Exception:
            pass
        try:
            info["length_mm"] = round(units.m_to_mm(segment.GetLength()), 4)
        except Exception:
            pass
        try:
            x, y, z = _segment_point(segment)
            info["point_mm"] = [round(units.m_to_mm(v), 4) for v in (x, y, z)]
        except Exception:
            pass
        infos.append(info)
    try:
        status = int(sketch.GetConstrainedStatus())
    except Exception:
        status = None
    return {
        "segments": infos,
        "segment_count": len(infos),
        "constrained_status": status,
    }


def select_segments(doc, indices: list[int], append: bool = False) -> None:
    sketch = _active_sketch(doc)
    segments = _wrap_segments(sketch.GetSketchSegments())
    first = not append
    data = inspect.create_select_data(doc)
    for index in indices:
        if not isinstance(index, int) or index < 0 or index >= len(segments):
            raise SelectionError(
                f"sketch segment index {index} out of range (0..{len(segments) - 1})"
            )
        if not inspect.select_entity(segments[index], not first, 0, data):
            raise SelectionError(f"could not select sketch segment {index}")
        first = False


def add_relation(relation: str, segment_indices: list[int]) -> dict:
    _, doc, _ = session.active_doc(("part",))
    _active_sketch(doc)
    session.clear_selection(doc)
    select_segments(doc, segment_indices)
    before = len(_wrap_segments(_active_sketch(doc).GetSketchSegments()))
    doc.SketchAddConstraints(relation)
    after = len(_wrap_segments(_active_sketch(doc).GetSketchSegments()))
    return {"relation": relation, "segments_unchanged": before == after}


INPUT_DIM_VAL_ON_CREATE = 10


def _suppress_dimension_dialog():
    """Turn off the modal Modify box for the duration of a dimension call.

    With swInputDimValOnCreate enabled, AddDimension2 opens a modal dialog
    that blocks the COM call that opened it (and has crashed the session).
    """
    app = session.app()
    try:
        original = bool(
            binding.value(app.GetUserPreferenceToggle(INPUT_DIM_VAL_ON_CREATE))
        )
    except Exception:
        return None
    if original:
        app.SetUserPreferenceToggle(INPUT_DIM_VAL_ON_CREATE, False)
    return original


def _restore_dimension_dialog(original) -> None:
    if original:
        try:
            session.app().SetUserPreferenceToggle(
                INPUT_DIM_VAL_ON_CREATE, True
            )
        except Exception:
            pass


def add_dimension(
    segment_indices: list[int],
    value_mm: float | None = None,
    placement_mm: list[float] | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    _active_sketch(doc)
    session.clear_selection(doc)
    select_segments(doc, segment_indices)
    px, py = (placement_mm or [0.0, 0.0])[:2]
    restore = _suppress_dimension_dialog()
    try:
        display_dimension = doc.AddDimension2(_mm(px), _mm(py), 0.0)
    finally:
        _restore_dimension_dialog(restore)
    if display_dimension is None:
        raise ComCallError(
            "SOLIDWORKS did not create a dimension for that selection",
            hint="Select a single line/circle/arc or two compatible entities.",
        )
    applied = False
    if value_mm is not None:
        value_m = _mm(value_mm)
        dimension = None
        for getter in ("GetDimension2", "GetDimension"):
            try:
                dimension = getattr(display_dimension, getter)(0) if getter == "GetDimension2" else getattr(display_dimension, getter)()
                if dimension is not None:
                    dimension = binding.wrap(dimension, "IDimension")
                    break
            except Exception:
                dimension = None
        if dimension is not None:
            for which_config in (1, 0, 2):
                try:
                    dimension.SetSystemValue3(value_m, which_config, None)
                except Exception:
                    continue
                try:
                    actual = float(dimension.GetSystemValue2(""))
                except Exception:
                    actual = None
                if actual is not None and abs(actual - value_m) < 1e-9:
                    applied = True
                    break
    return {
        "value_mm": value_mm,
        "value_applied": applied,
        "placement_mm": [px, py],
    }
