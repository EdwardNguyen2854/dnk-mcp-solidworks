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

# swSketchTrimChoice_e, measured off swconst.tlb (34.0).
TRIM_CHOICES = {
    "closest": 0,
    "corner": 1,
    "two_entities": 2,
    "entity_point": 3,
    "entities": 4,
    "outside": 5,
    "inside": 6,
}

# swSketchSlotLengthType_e, measured off swconst.tlb (34.0).
SLOT_LENGTH_TYPES = {"center_center": 0, "full_length": 1}

# swSketchSlotCreationType_e: a straight slot is drawn from a centerline.
SLOT_CREATION_LINE = 0


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
    _, doc, kind = session.active_doc(("part", "drawing"))
    manager = _sketch_manager(doc)
    if manager.ActiveSketch is None:
        raise SelectionError("no active sketch to exit")
    manager.InsertSketch(True)
    active = manager.ActiveSketch is not None
    result = {"active_sketch": active}
    if kind == "drawing" and active:
        # Measured on SW2026 SP0.0: neither InsertSketch nor EditSketch closes
        # a drawing view sketch; ActiveSketch also reports the active view's
        # sketch regardless of edit state, so it cannot be used as a signal.
        # The sketch is consumed by the next section or detail command.
        result["view_sketch"] = True
        result["note"] = (
            "SOLIDWORKS 2026 SP0.0 does not close a drawing view sketch through "
            "the API; geometry keeps collecting in the view's sketch until a "
            "section or detail command consumes it."
        )
    return result


def _require_sketch(func):
    def wrapper(*args, **kwargs):
        _, doc, _ = session.active_doc(("part", "drawing"))
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
def arc(doc, center_x_mm: float, center_y_mm: float, start_x_mm: float,
        start_y_mm: float, end_x_mm: float, end_y_mm: float,
        direction: int = 1) -> dict:
    if direction not in (1, -1):
        raise InvalidParameterError("direction must be 1 (CCW) or -1 (CW)")
    segment = _sketch_manager(doc).CreateArc(
        _mm(center_x_mm), _mm(center_y_mm), 0.0,
        _mm(start_x_mm), _mm(start_y_mm), 0.0,
        _mm(end_x_mm), _mm(end_y_mm), 0.0,
        int(direction),
    )
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def three_point_arc(doc, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float,
                    x3_mm: float, y3_mm: float) -> dict:
    segment = _sketch_manager(doc).Create3PointArc(
        _mm(x1_mm), _mm(y1_mm), 0.0,
        _mm(x2_mm), _mm(y2_mm), 0.0,
        _mm(x3_mm), _mm(y3_mm), 0.0,
    )
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def ellipse(doc, center_x_mm: float, center_y_mm: float, major_x_mm: float,
            major_y_mm: float, minor_x_mm: float, minor_y_mm: float) -> dict:
    segment = _sketch_manager(doc).CreateEllipse(
        _mm(center_x_mm), _mm(center_y_mm), 0.0,
        _mm(major_x_mm), _mm(major_y_mm), 0.0,
        _mm(minor_x_mm), _mm(minor_y_mm), 0.0,
    )
    return {"segments_created": 1 if segment else 0}


@_require_sketch
def slot(doc, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float,
         width_mm: float, length_type: str = "center_center",
         add_dimensions: bool = False) -> dict:
    if width_mm <= 0:
        raise InvalidParameterError("width_mm must be positive")
    code = SLOT_LENGTH_TYPES.get(length_type)
    if code is None:
        raise InvalidParameterError(
            f"unknown length_type {length_type!r}",
            available=sorted(SLOT_LENGTH_TYPES),
        )
    raw = _sketch_manager(doc).CreateSketchSlot(
        SLOT_CREATION_LINE,
        code,
        _mm(width_mm),
        _mm(x1_mm), _mm(y1_mm), 0.0,
        _mm(x2_mm), _mm(y2_mm), 0.0,
        0.0, 0.0, 0.0,
        1,
        bool(add_dimensions),
    )
    return {"segments_created": 1 if raw else 0}


@_require_sketch
def point(doc, x_mm: float, y_mm: float) -> dict:
    created = _sketch_manager(doc).CreatePoint(_mm(x_mm), _mm(y_mm), 0.0)
    return {"points_created": 1 if created else 0}


def _sketch_shape(doc) -> tuple[int, float]:
    """Fingerprint of the open sketch: segment count and total length."""
    sketch = _active_sketch(doc)
    segments = _wrap_segments(sketch.GetSketchSegments())
    total = 0.0
    for segment in segments:
        try:
            total += float(segment.GetLength())
        except Exception:
            continue
    return (len(segments), round(total, 9))


@_require_sketch
def sketch_fillet(doc, segment_indices: list[int], radius_mm: float,
                  keep_constraints: bool = True) -> dict:
    if radius_mm <= 0:
        raise InvalidParameterError("radius_mm must be positive")
    if len(segment_indices) != 2:
        raise InvalidParameterError(
            "a sketch fillet needs exactly two segments sharing a corner"
        )
    session.clear_selection(doc)
    select_segments(doc, segment_indices)
    before = _sketch_shape(doc)
    ok = bool(doc.SketchFillet2(_mm(radius_mm), 1 if keep_constraints else 0))
    session.clear_selection(doc)
    after = _sketch_shape(doc)
    if not ok and after == before:
        raise ComCallError(
            "SOLIDWORKS did not apply the sketch fillet",
            hint="Select two segments that share a corner and a radius that fits.",
        )
    return {"fillet": True, "radius_mm": radius_mm, "segments": after[0]}


@_require_sketch
def sketch_chamfer(doc, segment_indices: list[int], distance_mm: float,
                   angle_deg: float = 45.0, mode: str = "equal_distance") -> dict:
    if distance_mm <= 0:
        raise InvalidParameterError("distance_mm must be positive")
    if len(segment_indices) != 2:
        raise InvalidParameterError(
            "a sketch chamfer needs exactly two segments sharing a corner"
        )
    if mode == "distance_angle":
        # SketchChamfer(First, Second, Option): option 0 reads the angle first.
        first, second, option = units.deg_to_rad(angle_deg), _mm(distance_mm), 0
    elif mode == "equal_distance":
        first, second, option = _mm(distance_mm), _mm(distance_mm), 2
    else:
        raise InvalidParameterError(
            f"unknown mode {mode!r}",
            available=["equal_distance", "distance_angle"],
        )
    session.clear_selection(doc)
    select_segments(doc, segment_indices)
    before = _sketch_shape(doc)
    doc.SketchChamfer(first, second, option)
    session.clear_selection(doc)
    after = _sketch_shape(doc)
    if after == before:
        raise ComCallError(
            "SOLIDWORKS did not apply the sketch chamfer",
            hint="Select two segments that share a corner and a distance that fits.",
        )
    return {
        "chamfer": True,
        "distance_mm": distance_mm,
        "angle_deg": angle_deg,
        "segments": after[0],
    }


@_require_sketch
def trim(doc, segment_indices: list[int], x_mm: float, y_mm: float,
         mode: str = "closest") -> dict:
    option = TRIM_CHOICES.get(mode)
    if option is None:
        raise InvalidParameterError(
            f"unknown trim mode {mode!r}", available=sorted(TRIM_CHOICES)
        )
    if len(segment_indices) != 1:
        raise InvalidParameterError(
            "select exactly one segment in segment_indices; the point chooses "
            "which piece of it is removed"
        )
    session.clear_selection(doc)
    select_segments(doc, segment_indices)
    before = _sketch_shape(doc)
    # SketchTrim reports False even when it succeeds, so the sketch is the
    # judge: with no target selected it does nothing.
    _sketch_manager(doc).SketchTrim(option, _mm(x_mm), _mm(y_mm), 0.0)
    after = _sketch_shape(doc)
    session.clear_selection(doc)
    if after == before:
        raise ComCallError(
            "nothing was trimmed",
            hint="Give a point on the piece to remove, on the segment named in "
            "segment_indices.",
        )
    return {
        "segments_before": before[0],
        "segments_after": after[0],
        "trimmed": True,
    }


@_require_sketch
def mirror(doc, segment_indices: list[int], mirror_segment: int) -> dict:
    sketch = _active_sketch(doc)
    segments = _wrap_segments(sketch.GetSketchSegments())
    if not segment_indices:
        raise InvalidParameterError("segment_indices must not be empty")
    if not 0 <= mirror_segment < len(segments):
        raise SelectionError(
            f"mirror_segment {mirror_segment} out of range "
            f"(0..{len(segments) - 1})"
        )
    session.clear_selection(doc)
    select_segments(doc, segment_indices)
    if not inspect.select_entity(segments[mirror_segment], True, 0):
        raise SelectionError(
            f"could not add mirror segment {mirror_segment} to the selection"
        )
    before = _sketch_shape(doc)
    doc.SketchMirror()
    after = _sketch_shape(doc)
    session.clear_selection(doc)
    if after[0] <= before[0]:
        raise ComCallError(
            "SOLIDWORKS did not mirror the selection",
            hint="The mirror_segment must be a construction centerline.",
        )
    return {
        "segments_before": before[0],
        "segments_after": after[0],
        "mirror_segment": mirror_segment,
    }


@_require_sketch
def set_construction(doc, segment_indices: list[int],
                     construction: bool = True) -> dict:
    segments = _wrap_segments(_active_sketch(doc).GetSketchSegments())
    changed = 0
    for index in segment_indices:
        if not isinstance(index, int) or index < 0 or index >= len(segments):
            raise SelectionError(
                f"sketch segment index {index} out of range "
                f"(0..{len(segments) - 1})"
            )
        segments[index].ConstructionGeometry = bool(construction)
        changed += 1
    if not changed:
        raise InvalidParameterError("segment_indices must not be empty")
    return {"changed": changed, "construction": bool(construction)}


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


def list_sketches() -> dict:
    """List every sketch feature; read-only feed for edit_sketch and selection."""
    _, doc, _ = session.active_doc(("part", "drawing"))
    sketches = []
    for feature in session.iter_features(doc):
        try:
            kind = str(feature.GetTypeName2())
        except Exception:
            continue
        if kind not in ("ProfileFeature", "Sketch"):
            continue
        info = {"name": str(binding.value(feature.Name)), "type": kind}
        try:
            sketch = binding.wrap(feature.GetSpecificFeature2(), "ISketch")
            info["segments"] = len(_wrap_segments(sketch.GetSketchSegments()))
            info["constrained_status"] = int(sketch.GetConstrainedStatus())
        except Exception:
            pass
        sketches.append(info)
    active = _sketch_manager(doc).ActiveSketch is not None
    return {"sketches": sketches, "count": len(sketches), "sketch_open": active}


def edit_sketch(name: str) -> dict:
    """Reopen an existing sketch feature for editing."""
    _, doc, _ = session.active_doc(("part",))
    resolved = session.select_sketch(doc, name, append=False)
    manager = _sketch_manager(doc)
    manager.InsertSketch(True)
    if manager.ActiveSketch is None:
        # Older builds open an existing sketch through IModelDoc2.EditSketch
        # rather than through InsertSketch.
        try:
            doc.EditSketch()
        except Exception:
            pass
    if manager.ActiveSketch is None:
        raise ComCallError(
            f"SOLIDWORKS could not reopen sketch {resolved!r}",
            hint="Check the name from list_sketches and retry.",
        )
    return {"sketch": resolved, "active": True}


def list_sketch_segments() -> dict:
    _, doc, _ = session.active_doc(("part", "drawing"))
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
    _, doc, _ = session.active_doc(("part", "drawing"))
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
    _, doc, _ = session.active_doc(("part", "drawing"))
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


# swDimensionType_e, measured off swconst.tlb (34.0).
DIMENSION_KINDS = {
    0: "unknown",
    1: "ordinate",
    2: "linear",
    3: "angular",
    4: "arc_length",
    5: "radial",
    6: "diameter",
    7: "ordinate",
    8: "ordinate",
    9: "linear",
    10: "chamfer",
    11: "linear",
    12: "linear",
    13: "scalar",
    14: "radial",
    15: "diameter",
    16: "angular",
}
ANGULAR_KINDS = {"angular", "arc_length", "chamfer"}


def _display_dimensions(feature):
    try:
        current = feature.GetFirstDisplayDimension()
    except Exception:
        current = None
    guard = 0
    while current is not None and guard < 5000:
        guard += 1
        try:
            display = binding.wrap(current, "IDisplayDimension")
        except Exception:
            return
        yield display
        try:
            current = feature.GetNextDisplayDimension(current)
        except Exception:
            return


def _dimension_of(display):
    for getter, call in (("GetDimension2", True), ("GetDimension", False)):
        try:
            raw = getattr(display, getter)(0) if call else getattr(display, getter)()
            if raw is not None:
                return binding.wrap(raw, "IDimension")
        except Exception:
            continue
    return None


def _dimension_entry(owner: str, display, dimension) -> dict:
    full_name = str(binding.value(dimension.FullName) or "")
    entry: dict = {
        "owner": owner,
        "full_name": full_name,
        "name": str(binding.value(dimension.Name) or ""),
    }
    try:
        # IDisplayDimension carries the real dimension type here;
        # IDimension.GetType returns 0 for sketch dimensions on this build.
        kind = int(display.GetType())
    except Exception:
        try:
            kind = int(dimension.GetType())
        except Exception:
            kind = 0
    entry["kind"] = DIMENSION_KINDS.get(kind, f"type_{kind}")
    try:
        system_value = float(binding.value(dimension.SystemValue))
    except Exception:
        system_value = None
    if system_value is not None:
        if entry["kind"] in ANGULAR_KINDS:
            entry["value_deg"] = round(units.rad_to_deg(system_value), 6)
        else:
            entry["value_mm"] = round(units.m_to_mm(system_value), 6)
    return entry


def list_dimensions(feature_name: str | None = None) -> dict:
    """Read back driving dimensions with the names set_dimension accepts."""
    _, doc, _ = session.active_doc(("part", "drawing"))
    features = list(session.iter_features(doc))
    if feature_name is not None:
        resolved = session.resolve_name(
            feature_name,
            [str(binding.value(feature.Name)) for feature in features],
            "feature",
        )
        features = [
            feature
            for feature in features
            if str(binding.value(feature.Name)) == resolved
        ]
    dimensions = []
    for feature in features:
        owner = str(binding.value(feature.Name))
        for display in _display_dimensions(feature):
            dimension = _dimension_of(display)
            if dimension is None:
                continue
            try:
                dimensions.append(_dimension_entry(owner, display, dimension))
            except Exception:
                continue
    return {"dimensions": dimensions, "count": len(dimensions)}


def set_dimension(full_name: str, value_mm: float | None = None,
                  value_deg: float | None = None) -> dict:
    """Drive an existing dimension by name; verified by read-back."""
    if value_mm is None and value_deg is None:
        raise InvalidParameterError("pass value_mm or value_deg")
    _, doc, _ = session.active_doc(("part", "drawing"))
    raw = doc.Parameter(full_name)
    if raw is None:
        raise SelectionError(
            f"no dimension named {full_name!r}",
            hint="Call list_dimensions for the exact full_name values.",
        )
    dimension = binding.wrap(raw, "IDimension")
    target = _mm(value_mm) if value_mm is not None else units.deg_to_rad(value_deg)
    for which_config in (2, 1, 0):
        try:
            dimension.SetSystemValue3(target, which_config, None)
        except Exception:
            continue
        try:
            actual = float(binding.value(dimension.SystemValue))
        except Exception:
            actual = None
        if actual is not None and abs(actual - target) < 1e-9:
            if doc.SketchManager.ActiveSketch is None:
                inspect.rebuild(doc)
            return {
                "full_name": full_name,
                "value_mm": value_mm,
                "value_deg": value_deg,
                "applied": True,
            }
    raise ComCallError(
        f"SOLIDWORKS did not accept the new value for {full_name!r}",
        hint="The sketch may be over-defined; remove a conflicting relation or "
        "dimension first.",
    )
