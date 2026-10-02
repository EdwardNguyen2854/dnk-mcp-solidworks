"""Inspection: mass properties, bounding boxes, topology, model health."""
from __future__ import annotations

from ..com import binding, units
import math

from ..errors import ComCallError, InvalidParameterError, SelectionError
from . import session

BODY_TYPES = {"solid": 0, "sheet": 1, "wire": 2, "all": -1}

# ICurve members on this build: IsLine, IsCircle, IsEllipse, IsBcurve.
CURVE_TYPES = ("line", "circle", "ellipse", "bspline", "other")

# Direction filter for list_faces; matched within ~2.5 degrees.
NORMAL_DIRECTIONS = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}
_NORMAL_TOLERANCE = 0.999


def _bodies(doc, body_type: str = "all", visible_only: bool = True):
    part = binding.wrap(doc, "IPartDoc")
    body_code = BODY_TYPES.get(body_type)
    if body_code is None:
        raise SelectionError(
            f"unknown body type {body_type!r}", available=sorted(BODY_TYPES)
        )
    raw = part.GetBodies2(body_code, visible_only)
    return [binding.wrap(body, "IBody2") for body in raw or []]


def _faces(body):
    raw = body.GetFaces()
    return [binding.wrap(face, "IFace2") for face in raw or []]


def _edges(body):
    raw = body.GetEdges()
    return [binding.wrap(edge, "IEdge") for edge in raw or []]


def _vertices(body):
    raw = body.GetVertices()
    return [binding.wrap(vertex, "IVertex") for vertex in raw or []]


def _surface_name(face) -> str:
    try:
        surface = face.GetSurface()
        if surface is None:
            return "unknown"
        for name, check in (
            ("plane", "IsPlane"),
            ("cylinder", "IsCylinder"),
            ("cone", "IsCone"),
            ("sphere", "IsSphere"),
            ("torus", "IsTorus"),
        ):
            try:
                if binding.value(getattr(surface, check)):
                    return name
            except Exception:
                continue
    except Exception:
        pass
    return "other"


def _point_or_none(point):
    if point is None:
        return None
    try:
        return [float(value) for value in point]
    except TypeError:
        return None


def point_on_face(face) -> tuple[float, float, float]:
    """Return a point that provably lies on the face (metres).

    ``GetTessTriangles(False)`` returns values in *document* units (mm on
    this install) while the rest of the API is metres; the NoConversion=True
    form returns system units, so it is used here.
    """
    try:
        triangles = face.GetTessTriangles(True)
        if triangles and len(triangles) >= 9:
            return (
                float(triangles[0] + triangles[3] + triangles[6]) / 3.0,
                float(triangles[1] + triangles[4] + triangles[7]) / 3.0,
                float(triangles[2] + triangles[5] + triangles[8]) / 3.0,
            )
    except Exception:
        pass
    try:
        box = _point_or_none(binding.value(face.GetBox()))
        if box and len(box) >= 6:
            centre = (
                (box[0] + box[3]) / 2.0,
                (box[1] + box[4]) / 2.0,
                (box[2] + box[5]) / 2.0,
            )
            closest = _point_or_none(face.GetClosestPointOn(*centre))
            if closest and len(closest) >= 3:
                return (closest[0], closest[1], closest[2])
    except Exception:
        pass
    raise SelectionError("could not compute a point on the face")


def point_on_edge(edge) -> tuple[float, float, float]:
    point = _point_or_none(binding.value(edge.Evaluate(0.5)))
    if point and len(point) >= 3:
        return (point[0], point[1], point[2])
    raise SelectionError("could not compute a point on the edge")


def face_details(face) -> dict:
    details = {"surface": _surface_name(face)}
    try:
        details["area_mm2"] = round(units.m2_to_mm2(face.GetArea()), 6)
    except Exception:
        pass
    try:
        normal = _point_or_none(binding.value(face.Normal))
        if normal and len(normal) >= 3:
            details["normal"] = [round(value, 6) for value in normal[:3]]
    except Exception:
        pass
    try:
        box = _point_or_none(binding.value(face.GetBox()))
        if box and len(box) >= 6:
            details["box_mm"] = {
                "min": [round(units.m_to_mm(v), 4) for v in box[0:3]],
                "max": [round(units.m_to_mm(v), 4) for v in box[3:6]],
            }
    except Exception:
        pass
    return details


def _curve_length(edge) -> float | None:
    try:
        curve = edge.GetCurve()
        params = edge.GetCurveParams()
        start_param, end_param = float(params[6]), float(params[7])
        return float(curve.GetLength3(start_param, end_param))
    except Exception:
        pass
    try:
        curve = edge.GetCurve()
        return float(curve.GetLength3(0.0, 1.0))
    except Exception:
        return None


def _curve_name(edge) -> str:
    try:
        curve = edge.GetCurve()
        if curve is None:
            return "other"
        for name, check in (
            ("line", "IsLine"),
            ("circle", "IsCircle"),
            ("ellipse", "IsEllipse"),
            ("bspline", "IsBcurve"),
        ):
            try:
                if binding.value(getattr(curve, check)):
                    return name
            except Exception:
                continue
    except Exception:
        pass
    return "other"


def edge_details(edge) -> dict:
    details = {"curve": _curve_name(edge)}
    if details["curve"] == "circle":
        try:
            curve = binding.wrap(edge.GetCurve(), "ICurve")
            circle = list(binding.value(curve.CircleParams))
            if len(circle) >= 7:
                details["center_mm"] = [round(units.m_to_mm(v), 6) for v in circle[:3]]
                details["axis"] = [float(v) for v in circle[3:6]]
                details["radius_mm"] = round(units.m_to_mm(circle[6]), 6)
        except Exception:
            pass
    length = _curve_length(edge)
    if length is not None:
        details["length_mm"] = round(units.m_to_mm(length), 6)
    try:
        raw_start = edge.GetStartVertex()
        raw_end = edge.GetEndVertex()
        if raw_start is None and raw_end is None:
            details["closed"] = True
            details["endpoint_source"] = "no_vertices"
            return details
        start = (
            _point_or_none(binding.wrap(raw_start, "IVertex").GetPoint())
            if raw_start is not None
            else None
        )
        end = (
            _point_or_none(binding.wrap(raw_end, "IVertex").GetPoint())
            if raw_end is not None
            else None
        )
        if start and len(start) >= 3 and end and len(end) >= 3:
            details["start_mm"] = [round(units.m_to_mm(v), 6) for v in start[:3]]
            details["end_mm"] = [round(units.m_to_mm(v), 6) for v in end[:3]]
            details["closed"] = sum(
                (start[axis] - end[axis]) ** 2 for axis in range(3)
            ) <= 1e-18
            details["endpoint_source"] = "trimmed_vertices"
        else:
            details["closed"] = False
            details["endpoint_source"] = "partial_vertices"
    except Exception:
        # Do not substitute curve parameter samples: they can describe the
        # untrimmed support curve and lie far outside the edge's actual span.
        details["closed"] = None
        details["endpoint_source"] = "unavailable"
    return details


def vertex_details(vertex) -> dict:
    details = {}
    try:
        point = _point_or_none(binding.value(vertex.GetPoint()))
        if point and len(point) >= 3:
            details["point_mm"] = [round(units.m_to_mm(v), 4) for v in point[:3]]
    except Exception:
        pass
    return details


def list_bodies(doc=None) -> list[dict]:
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    result = []
    for index, body in enumerate(_bodies(doc)):
        info = {"index": index, "name": str(binding.value(body.Name))}
        try:
            box = _point_or_none(binding.value(body.GetBodyBox()))
            if box and len(box) >= 6:
                info["box_mm"] = {
                    "min": [round(units.m_to_mm(v), 4) for v in box[0:3]],
                    "max": [round(units.m_to_mm(v), 4) for v in box[3:6]],
                }
        except Exception:
            pass
        info["face_count"] = len(_faces(body))
        info["edge_count"] = len(_edges(body))
        result.append(info)
    return result


def _normal_matches(normal, direction: str) -> bool:
    if not normal or len(normal) < 3:
        return False
    target = NORMAL_DIRECTIONS[direction]
    dot = sum(float(normal[index]) * target[index] for index in range(3))
    return dot >= _NORMAL_TOLERANCE


def list_faces(
    doc=None,
    body_type: str = "all",
    surface_type: str | None = None,
    min_area_mm2: float | None = None,
    normal: str | None = None,
) -> list[dict]:
    """List faces, optionally filtered.

    Filtered results keep the global selection index they would have in an
    unfiltered listing, so the output still feeds select_faces, shell, draft
    and measure directly.
    """
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    if surface_type is not None and surface_type not in ("plane", "cylinder", "cone",
                                                         "sphere", "torus", "other"):
        raise SelectionError(
            f"unknown surface type {surface_type!r}",
            available=["plane", "cylinder", "cone", "sphere", "torus", "other"],
        )
    if normal is not None and normal not in NORMAL_DIRECTIONS:
        raise SelectionError(
            f"unknown normal direction {normal!r}", available=sorted(NORMAL_DIRECTIONS)
        )
    faces = []
    index = 0
    for body_index, body in enumerate(_bodies(doc, body_type)):
        for face in _faces(body):
            info = {"index": index, "body": body_index}
            info.update(face_details(face))
            if surface_type is not None and info.get("surface") != surface_type:
                index += 1
                continue
            if min_area_mm2 is not None and info.get("area_mm2", 0.0) < min_area_mm2:
                index += 1
                continue
            if normal is not None and not _normal_matches(info.get("normal"), normal):
                index += 1
                continue
            faces.append(info)
            index += 1
    return faces


def list_edges(
    doc=None,
    body_type: str = "all",
    curve_type: str | None = None,
    min_length_mm: float | None = None,
) -> list[dict]:
    """List edges, optionally filtered (global indices preserved)."""
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    if curve_type is not None and curve_type not in CURVE_TYPES:
        raise SelectionError(
            f"unknown curve type {curve_type!r}", available=list(CURVE_TYPES)
        )
    edges = []
    index = 0
    for body_index, body in enumerate(_bodies(doc, body_type)):
        for edge in _edges(body):
            info = {"index": index, "body": body_index}
            info.update(edge_details(edge))
            if curve_type is not None and info.get("curve") != curve_type:
                index += 1
                continue
            if min_length_mm is not None and info.get("length_mm", 0.0) < min_length_mm:
                index += 1
                continue
            edges.append(info)
            index += 1
    return edges


def list_vertices(doc=None, body_type: str = "all") -> list[dict]:
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    vertices = []
    index = 0
    for body_index, body in enumerate(_bodies(doc, body_type)):
        for vertex in _vertices(body):
            info = {"index": index, "body": body_index}
            info.update(vertex_details(vertex))
            vertices.append(info)
            index += 1
    return vertices


def create_select_data(doc, mark: int = 0):
    """Build an ISelectData carrying a mark, the modern selection path.

    ``IModelDoc2.SelectionManager`` returns an untyped dispatch, so it is
    wrapped before ``CreateSelectData`` is called.
    """
    try:
        manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
        data = manager.CreateSelectData()
        if data is not None:
            data.Mark = mark
        return data
    except Exception:
        return None


def select_entity(entity, append: bool, mark: int = 0, data=None) -> bool:
    """Select a topology entity through the IEntity interface.

    The generated IFace2/IEdge classes expose no Select* members; the same
    COM object QueryInterfaced to IEntity does. Select4 with an ISelectData
    carries marks; Select2/Select are fallbacks.
    """
    target = entity
    try:
        target = binding.wrap(entity, "IEntity")
    except Exception:
        pass
    if data is not None:
        try:
            if target.Select4(append, data):
                return True
        except Exception:
            pass
    try:
        if target.Select2(append, mark):
            return True
    except Exception:
        pass
    try:
        return bool(target.Select(append))
    except Exception:
        return False


def _select_collection(doc, entities, indices, kind, append, mark) -> int:
    first = not append
    data = create_select_data(doc, mark)
    for index in indices:
        if not isinstance(index, int) or index < 0 or index >= len(entities):
            raise SelectionError(
                f"{kind.lower()} index {index} out of range "
                f"(0..{len(entities) - 1})"
            )
        if not select_entity(entities[index], not first, mark, data):
            raise SelectionError(f"could not select {kind.lower()} {index}")
        first = False
    return len(indices)


def select_faces(doc, indices: list[int], append: bool = False, mark: int = 0) -> int:
    faces = []
    for body in _bodies(doc):
        faces.extend(_faces(body))
    return _select_collection(doc, faces, indices, "FACE", append, mark)


def select_edges(doc, indices: list[int], append: bool = False, mark: int = 0) -> int:
    edges = []
    for body in _bodies(doc):
        edges.extend(_edges(body))
    return _select_collection(doc, edges, indices, "EDGE", append, mark)


def select_vertices(doc, indices: list[int], append: bool = False, mark: int = 0) -> int:
    vertices = []
    for body in _bodies(doc):
        vertices.extend(_vertices(body))
    return _select_collection(doc, vertices, indices, "VERTEX", append, mark)


def topology_entities(doc, kind: str) -> list:
    """Raw entities in the same global index order the list_* tools report.

    ``kind`` is ``face``, ``edge``, or ``vertex``. References need the raw
    objects to compare persistent ids; listing tools return plain dicts.
    """
    if kind not in ("face", "edge", "vertex"):
        raise InvalidParameterError(f"unknown topology kind {kind!r}")
    entities = []
    for body in _bodies(doc):
        if kind == "face":
            entities.extend(_faces(body))
        elif kind == "edge":
            entities.extend(_edges(body))
        else:
            entities.extend(_vertices(body))
    return entities


def select_bodies(doc, indices: list[int], append: bool = False, mark: int = 0) -> int:
    """Select solid bodies through IBody2.Select2.

    ``select_entity`` cannot select a body: IBody2 has no Select4, and its
    two-argument Select2 takes an ISelectData, not a mark. This is the
    measured path for up-to-body extrusions and later body operations.
    """
    bodies = _bodies(doc)
    first = not append
    data = create_select_data(doc, mark)
    if data is None:
        raise ComCallError("could not create selection data for body selection")
    for index in indices:
        if not isinstance(index, int) or index < 0 or index >= len(bodies):
            raise SelectionError(
                f"body index {index} out of range (0..{len(bodies) - 1})"
            )
        if not bodies[index].Select2(not first, data):
            raise SelectionError(f"could not select body {index}")
        first = False
    return len(indices)


MASS_PROPERTY_ACCURACY = {"standard": None, "maximum": 2}


def mass_properties(doc=None, accuracy: str = "standard") -> dict:
    if accuracy not in MASS_PROPERTY_ACCURACY:
        raise InvalidParameterError(
            f"unknown mass-property accuracy {accuracy!r}",
            available=sorted(MASS_PROPERTY_ACCURACY),
        )
    if doc is None:
        _, doc, _ = session.active_doc(("part", "assembly"))
    mass_prop = doc.Extension.CreateMassProperty()
    if mass_prop is None:
        raise ComCallError("CreateMassProperty returned None")
    mass_prop = binding.wrap(mass_prop, "IMassProperty")
    result: dict = {}
    # Density must be read first: on a freshly created mass-property object,
    # reading geometry members first makes Density (and Mass) fall back to
    # the default 1.0 value even when a material is assigned.
    try:
        result["density_kg_m3"] = round(float(binding.value(mass_prop.Density)), 6)
    except Exception:
        pass
    scalars = (
        ("Volume", units.m3_to_mm3, "volume_mm3"),
        ("Area", units.m2_to_mm2, "area_mm2"),
        ("Mass", lambda v: v * 1000.0, "mass_g"),
    )
    for member, convert, key in scalars:
        try:
            result[key] = round(convert(float(binding.value(getattr(mass_prop, member)))), 6)
        except Exception:
            continue
    try:
        centre = _point_or_none(binding.value(mass_prop.CenterOfMass))
        if centre and len(centre) >= 3:
            result["center_of_mass_mm"] = [round(units.m_to_mm(v), 4) for v in centre[:3]]
    except Exception:
        pass
    result["accuracy"] = accuracy
    result["status"] = None
    result["method"] = "CreateMassProperty"
    if accuracy == "maximum":
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
        raw = extension.GetMassProperties2(2, 0, False)
        values, out_values = session.com_result(raw, 1)
        values = _point_or_none(binding.value(values))
        status = out_values[0]
        if values is None or len(values) < 6:
            raise ComCallError(
                "GetMassProperties2 returned incomplete maximum-accuracy data",
                status=status,
            )
        result.update(
            {
                "mass_g": round(float(values[5]) * 1000.0, 6),
                "volume_mm3": round(units.m3_to_mm3(float(values[3])), 6),
                "area_mm2": round(units.m2_to_mm2(float(values[4])), 6),
                "center_of_mass_mm": [
                    round(units.m_to_mm(float(value)), 6) for value in values[:3]
                ],
                "status": int(status) if status is not None else None,
                "method": "GetMassProperties2",
            }
        )
        if status is not None and int(status) != 0:
            raise ComCallError(
                "GetMassProperties2 did not report a successful status",
                status=int(status),
                measurements={key: result.get(key) for key in (
                    "mass_g", "volume_mm3", "area_mm2"
                )},
            )
    return result


def bounding_box(doc=None) -> dict:
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    bodies = _bodies(doc, "solid")
    if not bodies:
        raise ComCallError("no solid bodies are available for exact extrema")
    minimum = [float("inf")] * 3
    maximum = [float("-inf")] * 3
    for body in bodies:
        for axis in range(3):
            direction = [0.0, 0.0, 0.0]
            direction[axis] = 1.0
            max_raw = body.GetExtremePoint(*direction, 0.0, 0.0, 0.0)
            max_ok, max_out = session.com_result(max_raw, 3)
            direction[axis] = -1.0
            min_raw = body.GetExtremePoint(*direction, 0.0, 0.0, 0.0)
            min_ok, min_out = session.com_result(min_raw, 3)
            if not max_ok or not min_ok or len(max_out) < 3 or len(min_out) < 3:
                raise ComCallError(
                    "IBody2.GetExtremePoint failed",
                    body=str(binding.value(body.Name) or ""),
                    axis="xyz"[axis],
                )
            try:
                max_point = [float(value) for value in max_out]
                min_point = [float(value) for value in min_out]
            except (TypeError, ValueError) as exc:
                raise ComCallError("GetExtremePoint returned invalid coordinates") from exc
            maximum[axis] = max(maximum[axis], max_point[axis])
            minimum[axis] = min(minimum[axis], min_point[axis])
    minimum = [round(units.m_to_mm(value), 6) for value in minimum]
    maximum = [round(units.m_to_mm(value), 6) for value in maximum]
    return {
        "min_mm": minimum,
        "max_mm": maximum,
        "size_mm": [round(maximum[i] - minimum[i], 4) for i in range(3)],
        "accuracy": "exact_extreme_point",
    }


def _dot(first, second) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _point_segment_distance_sq(point, first, second) -> float:
    direction = [second[i] - first[i] for i in range(3)]
    length_sq = _dot(direction, direction)
    if length_sq <= 1e-30:
        return _dot([point[i] - first[i] for i in range(3)],
                    [point[i] - first[i] for i in range(3)])
    offset = [point[i] - first[i] for i in range(3)]
    parameter = max(0.0, min(1.0, _dot(offset, direction) / length_sq))
    closest = [first[i] + parameter * direction[i] for i in range(3)]
    delta = [point[i] - closest[i] for i in range(3)]
    return _dot(delta, delta)


def _point_triangle_distance_sq(point, triangle) -> float:
    """Closest squared distance to a triangle, including its edge regions."""
    first, second, third = triangle
    ab = [second[i] - first[i] for i in range(3)]
    ac = [third[i] - first[i] for i in range(3)]
    ap = [point[i] - first[i] for i in range(3)]
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return _dot(ap, ap)
    bp = [point[i] - second[i] for i in range(3)]
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return _dot(bp, bp)
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return _point_segment_distance_sq(point, first, second)
    cp = [point[i] - third[i] for i in range(3)]
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return _dot(cp, cp)
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return _point_segment_distance_sq(point, first, third)
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        return _point_segment_distance_sq(point, second, third)
    denom = va + vb + vc
    if abs(denom) <= 1e-30:
        return min(
            _point_segment_distance_sq(point, first, second),
            _point_segment_distance_sq(point, second, third),
            _point_segment_distance_sq(point, third, first),
        )
    inverse = 1.0 / denom
    v, w = vb * inverse, vc * inverse
    closest = [first[i] + ab[i] * v + ac[i] * w for i in range(3)]
    delta = [point[i] - closest[i] for i in range(3)]
    return _dot(delta, delta)


def _surface_triangles(doc, limit: int = 512) -> tuple[list, int]:
    triangles = []
    missing_faces = 0
    for body in _bodies(doc, "solid"):
        for face in _faces(body):
            try:
                raw = binding.value(face.GetTessTriangles(True))
                values = [float(value) for value in raw or []]
            except Exception:
                missing_faces += 1
                continue
            if not values or len(values) % 9 or not all(math.isfinite(value) for value in values):
                missing_faces += 1
                continue
            for offset in range(0, len(values) - 8, 9):
                triangles.append(
                    tuple(
                        tuple(values[offset + vertex * 3 + axis] for axis in range(3))
                        for vertex in range(3)
                    )
                )
    if missing_faces:
        raise ComCallError("surface comparison requires tessellation for every solid face",
                           faces_without_valid_tessellation=missing_faces)
    total = len(triangles)
    if total > limit:
        step = total / float(limit)
        triangles = [triangles[int(index * step)] for index in range(limit)]
    return triangles, total


def _directed_sampled_deviation(source: list, target: list) -> float:
    points = [point for triangle in source for point in triangle]
    if not points or not target:
        raise ComCallError("surface tessellation is unavailable for comparison")
    return max(
        math.sqrt(min(_point_triangle_distance_sq(point, triangle) for triangle in target))
        for point in points
    )


def _topology_summary(doc) -> dict:
    bodies = _bodies(doc, "solid")
    return {
        "bodies": len(bodies),
        "faces": sum(len(_faces(body)) for body in bodies),
        "edges": sum(len(_edges(body)) for body in bodies),
    }


def compare_model_geometry(
    reference_model: str,
    volume_tolerance_mm3: float,
    extrema_tolerance_mm: float,
    surface_tolerance_mm: float,
) -> dict:
    """Compare the active part with another already-open part.

    Surface deviation is the bidirectional maximum from a deterministic sample
    of tessellated triangle vertices to a capped triangle sample. It is useful
    for review but is not an analytic Hausdorff-distance proof.
    """
    tolerances = {
        "volume_mm3": volume_tolerance_mm3,
        "extrema_mm": extrema_tolerance_mm,
        "surface_mm": surface_tolerance_mm,
    }
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in tolerances.values()):
        raise InvalidParameterError("all geometry comparison tolerances must be finite and positive")
    application, current, _ = session.active_doc(("part",))
    if not isinstance(reference_model, str) or not reference_model.strip():
        raise InvalidParameterError("reference_model is required")
    wanted = reference_model.strip()
    normalized = wanted.replace("/", "\\").rstrip("\\").casefold()
    matches = []
    for raw in application.GetDocuments() or []:
        try:
            candidate = session.wrap_doc(raw)
            if int(candidate.GetType()) != 1:
                continue
            path = str(binding.value(candidate.GetPathName) or "")
            title = str(binding.value(candidate.GetTitle) or "")
        except Exception:
            continue
        candidate_path = path.replace("/", "\\").rstrip("\\").casefold()
        if normalized == candidate_path or wanted.casefold() == title.casefold():
            matches.append((candidate, path or title))
    if len(matches) != 1:
        raise SelectionError(
            "reference_model must identify exactly one other open part",
            reference_model=wanted,
            matches=[item[1] for item in matches],
        )
    reference, reference_id = matches[0]
    current_doc_info = session.doc_info(current)
    current_id = str(current_doc_info.get("path") or current_doc_info.get("title") or "")
    if reference is current or (
        current_id and reference_id.replace("/", "\\").casefold()
        == current_id.replace("/", "\\").casefold()
    ):
        raise InvalidParameterError("reference_model must differ from the active part")
    current_info = {
        "mass": mass_properties(current, "maximum"),
        "bounds": bounding_box(current),
        "topology": _topology_summary(current),
    }
    reference_info = {
        "mass": mass_properties(reference, "maximum"),
        "bounds": bounding_box(reference),
        "topology": _topology_summary(reference),
    }
    volume_delta = abs(
        current_info["mass"]["volume_mm3"] - reference_info["mass"]["volume_mm3"]
    )
    axis_deltas = {}
    for axis, label in enumerate("xyz"):
        axis_deltas[label] = {
            "min_mm": abs(
                current_info["bounds"]["min_mm"][axis]
                - reference_info["bounds"]["min_mm"][axis]
            ),
            "max_mm": abs(
                current_info["bounds"]["max_mm"][axis]
                - reference_info["bounds"]["max_mm"][axis]
            ),
        }
    max_extrema_delta = max(
        value for bounds in axis_deltas.values() for value in bounds.values()
    )
    current_mesh, current_triangle_count = _surface_triangles(current)
    reference_mesh, reference_triangle_count = _surface_triangles(reference)
    surface_delta_m = max(
        _directed_sampled_deviation(current_mesh, reference_mesh),
        _directed_sampled_deviation(reference_mesh, current_mesh),
    )
    surface_delta_mm = units.m_to_mm(surface_delta_m)
    passed = (
        volume_delta <= float(volume_tolerance_mm3)
        and max_extrema_delta <= float(extrema_tolerance_mm)
        and surface_delta_mm <= float(surface_tolerance_mm)
    )
    return {
        "data": {
            "reference_model": reference_id,
            "active_model": current_doc_info,
            "passed": passed,
            "tolerance_basis": "measured_volume_extrema_and_sampled_surface",
            "release_equivalence_proven": False,
            "tolerances": tolerances,
            "deltas": {
                "volume_mm3": round(volume_delta, 9),
                "extrema_mm": axis_deltas,
                "max_extrema_mm": round(max_extrema_delta, 9),
                "sampled_surface_deviation_mm": round(surface_delta_mm, 9),
            },
            "topology": {
                "active": current_info["topology"],
                "reference": reference_info["topology"],
            },
            "surface_method": {
                "name": "bidirectional_tessellated_vertex_to_triangle_sample",
                "active_triangles_total": current_triangle_count,
                "reference_triangles_total": reference_triangle_count,
                "triangles_sampled": {"active": len(current_mesh), "reference": len(reference_mesh)},
                "exact_analytic_distance": False,
            },
        },
        "evidence": {"active": current_info, "reference": reference_info},
    }


EXTRUDE_DEFINITION_TYPES = {"Boss", "Extrusion", "Cut", "BossThin", "CutThin"}


def editable_feature_diagnostics(doc=None) -> dict:
    """Read feature types and known editable parameters without changing data.

    The shipped typelib exposes directional depth getters on
    ``IExtrudeFeatureData2``. Other feature families are deliberately marked
    unavailable until their definition members have been probed and verified.
    """
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    features = []
    for feature in session.iter_features(doc):
        try:
            name = str(binding.value(feature.Name) or "")
            kind = str(feature.GetTypeName2() or "")
        except Exception:
            continue
        item = {"name": name, "type": kind, "editable_parameters": {}}
        if kind not in EXTRUDE_DEFINITION_TYPES:
            item["definition_status"] = "not_probed"
            features.append(item)
            continue
        try:
            raw_definition = feature.GetDefinition()
            if raw_definition is None:
                raise ComCallError("GetDefinition returned None")
            definition = binding.wrap(raw_definition, "IExtrudeFeatureData2")
            item["definition_interface"] = "IExtrudeFeatureData2"
            item["editable_parameters"] = {
                "depth_forward_mm": round(
                    units.m_to_mm(float(binding.value(definition.GetDepth(True)))), 6
                ),
                "depth_reverse_mm": round(
                    units.m_to_mm(float(binding.value(definition.GetDepth(False)))), 6
                ),
            }
            item["definition_status"] = "read_back"
        except Exception as exc:
            item["definition_status"] = "read_failed"
            item["definition_error"] = f"{type(exc).__name__}: {exc}"
        features.append(item)
    return {
        "features": features,
        "count": len(features),
        "supported_definition_types": sorted(EXTRUDE_DEFINITION_TYPES),
        "unsupported_parameters_are_not_inferred": True,
    }


# Readings IMeasure exposes; SOLIDWORKS reports -1 for the ones that do not
# apply to the current selection.
MEASURE_READINGS = (
    ("Length", "length_mm", units.m_to_mm),
    ("TotalLength", "total_length_mm", units.m_to_mm),
    ("ArcLength", "arc_length_mm", units.m_to_mm),
    ("ChordLength", "chord_length_mm", units.m_to_mm),
    ("Perimeter", "perimeter_mm", units.m_to_mm),
    ("Area", "area_mm2", units.m2_to_mm2),
    ("TotalArea", "total_area_mm2", units.m2_to_mm2),
    ("Distance", "distance_mm", units.m_to_mm),
    ("NormalDistance", "normal_distance_mm", units.m_to_mm),
    ("CenterDistance", "center_distance_mm", units.m_to_mm),
    ("DeltaX", "delta_x_mm", units.m_to_mm),
    ("DeltaY", "delta_y_mm", units.m_to_mm),
    ("DeltaZ", "delta_z_mm", units.m_to_mm),
    ("Angle", "angle_deg", units.rad_to_deg),
    ("Diameter", "diameter_mm", units.m_to_mm),
    ("Radius", "radius_mm", units.m_to_mm),
)


def measure(face_indices: list[int] | None = None,
            edge_indices: list[int] | None = None,
            vertex_indices: list[int] | None = None) -> dict:
    """Measure selected topology with IModelDocExtension.CreateMeasure.

    One face gives area and perimeter, one edge its length, two entities the
    distance and delta between them.
    """
    _, doc, _ = session.active_doc(("part", "assembly"))
    session.clear_selection(doc)
    count = 0
    first = True
    for indices, selector in (
        (face_indices, select_faces),
        (edge_indices, select_edges),
        (vertex_indices, select_vertices),
    ):
        if not indices:
            continue
        count += selector(doc, indices, append=not first)
        first = False
    if count == 0:
        raise InvalidParameterError(
            "pass face_indices, edge_indices or vertex_indices to measure"
        )
    measurement = binding.value(doc.Extension.CreateMeasure)
    if measurement is None:
        session.clear_selection(doc)
        raise ComCallError("SOLIDWORKS did not provide a measure object")
    measurement = binding.wrap(measurement, "IMeasure")
    try:
        measurement.ArcOption = 0
    except Exception:
        pass
    try:
        ok = bool(measurement.Calculate(None))
    except Exception:
        try:
            ok = bool(binding.value(measurement.Calculate))
        except Exception:
            ok = False
    if not ok:
        session.clear_selection(doc)
        raise ComCallError(
            "SOLIDWORKS could not measure that selection", entities=count
        )
    readings: dict = {}
    for member, key, convert in MEASURE_READINGS:
        try:
            raw = binding.value(getattr(measurement, member))
        except Exception:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if number < 0:
            continue
        readings[key] = round(convert(number), 6)
    session.clear_selection(doc)
    if not readings:
        raise ComCallError(
            "the measurement returned no readings",
            hint="Try a face, an edge, or two entities of the same kind.",
        )
    return {"entities": count, **readings}


def whats_wrong(doc) -> dict:
    ext = doc.Extension
    count = int(ext.GetWhatsWrongCount())
    if count == 0:
        return {"count": 0, "features": [], "errors": [], "warnings": []}
    _ok_value, (features, codes, warnings) = session.com_result(
        ext.GetWhatsWrong(None, None, None), 3
    )
    names = []
    for raw in features or []:
        try:
            names.append(str(binding.value(binding.wrap(raw, "IFeature").Name)))
        except Exception:
            names.append("<unknown>")
    return {
        "count": count,
        "features": names,
        "errors": list(codes or []),
        "warnings": list(warnings or []),
    }


def rebuild(doc, top_only: bool = False) -> dict:
    ok = bool(doc.ForceRebuild3(top_only))
    return {"ok": ok, "whats_wrong": whats_wrong(doc)}


def model_evidence(doc=None, *, include_bbox: bool = True) -> dict:
    """Measured state used as evidence for every mutation."""
    if doc is None:
        _, doc, _ = session.active_doc(("part", "assembly"))
    evidence: dict = {}
    try:
        evidence["mass_properties"] = mass_properties(doc)
    except Exception:
        pass
    if include_bbox and session.DOC_TYPES.get(int(doc.GetType())) == "part":
        try:
            evidence["bounding_box"] = bounding_box(doc)
        except Exception:
            pass
    try:
        evidence["features"] = list_feature_infos(doc)
    except Exception:
        pass
    return evidence
