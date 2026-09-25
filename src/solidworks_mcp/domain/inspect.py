"""Inspection: mass properties, bounding boxes, topology, model health."""
from __future__ import annotations

from ..com import binding, units
from ..errors import ComCallError, SelectionError
from . import session

BODY_TYPES = {"solid": 0, "sheet": 1, "wire": 2, "all": -1}


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


def edge_details(edge) -> dict:
    details = {}
    length = _curve_length(edge)
    if length is not None:
        details["length_mm"] = round(units.m_to_mm(length), 6)
    for key, parameter in (("start_mm", 0.0), ("end_mm", 1.0)):
        try:
            point = _point_or_none(binding.value(edge.Evaluate(parameter)))
            if point and len(point) >= 3:
                details[key] = [round(units.m_to_mm(v), 4) for v in point[:3]]
        except Exception:
            continue
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


def list_faces(doc=None, body_type: str = "all") -> list[dict]:
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    faces = []
    index = 0
    for body_index, body in enumerate(_bodies(doc, body_type)):
        for face in _faces(body):
            info = {"index": index, "body": body_index}
            info.update(face_details(face))
            faces.append(info)
            index += 1
    return faces


def list_edges(doc=None, body_type: str = "all") -> list[dict]:
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    edges = []
    index = 0
    for body_index, body in enumerate(_bodies(doc, body_type)):
        for edge in _edges(body):
            info = {"index": index, "body": body_index}
            info.update(edge_details(edge))
            edges.append(info)
            index += 1
    return edges


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


def mass_properties(doc=None) -> dict:
    if doc is None:
        _, doc, _ = session.active_doc(("part", "assembly"))
    mass_prop = doc.Extension.CreateMassProperty()
    if mass_prop is None:
        raise ComCallError("CreateMassProperty returned None")
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
    return result


def bounding_box(doc=None) -> dict:
    if doc is None:
        _, doc, _ = session.active_doc(("part",))
    part = binding.wrap(doc, "IPartDoc")
    box = _point_or_none(binding.value(part.GetPartBox(True)))
    if not box or len(box) < 6:
        raise ComCallError("GetPartBox returned no geometry")
    minimum = [round(units.m_to_mm(v), 4) for v in box[0:3]]
    maximum = [round(units.m_to_mm(v), 4) for v in box[3:6]]
    return {
        "min_mm": minimum,
        "max_mm": maximum,
        "size_mm": [round(maximum[i] - minimum[i], 4) for i in range(3)],
    }


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
