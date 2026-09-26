"""Solid features: extrude, cut, revolve, fillet, chamfer, shell, material."""
from __future__ import annotations

from ..com import binding, units
from ..errors import (
    ComCallError,
    FeatureBuildError,
    InvalidParameterError,
    SelectionError,
)
from . import inspect, session

END_CONDITIONS = {
    "blind": 0,
    "through_all": 1,
    "through_all_both": 9,
    "up_to_next": 11,
    "up_to_vertex": 3,
    "mid_plane": 6,
}
REVOLVE_BLIND = 0
CHAMFER_EQUAL_DISTANCE = 1
PLANE_CONSTRAINTS = {
    "parallel": 1,
    "perpendicular": 2,
    "coincident": 4,
    "distance": 8,
    "angle": 16,
    "midplane": 128,
    "flip": 256,
}


def _last_feature(doc):
    feature = doc.FirstFeature()
    last = None
    while feature:
        last = binding.wrap(feature, "IFeature")
        feature = last.GetNextFeature()
    return last


def _require_feature_result(doc, feature, operation: str) -> dict:
    if feature is None:
        raise FeatureBuildError(
            f"{operation} did not build",
            hint="Check the profile and end conditions; "
            "call list_features / whats_wrong for details.",
            whats_wrong=inspect.whats_wrong(doc),
        )
    wrapped = binding.wrap(feature, "IFeature")
    return {"feature": str(binding.value(wrapped.Name))}


def _rename(feature_name: str, new_name: str | None) -> None:
    if not new_name:
        return
    _, doc, _ = session.active_doc(("part",))
    for feature in session.iter_features(doc):
        if str(binding.value(feature.Name)) == feature_name:
            try:
                feature.Name = new_name
            except Exception:
                pass
            return


def _newest_feature_name(doc, before: set[str]) -> str | None:
    names = []
    for feature in session.iter_features(doc):
        try:
            names.append(str(binding.value(feature.Name)))
        except Exception:
            continue
    new = [item for item in names if item not in before]
    return new[-1] if new else None


def feature_names(doc) -> set[str]:
    names = set()
    for feature in session.iter_features(doc):
        try:
            names.add(str(binding.value(feature.Name)))
        except Exception:
            continue
    return names


def _finish_feature(
    doc, feature, operation: str, name: str | None, before: set[str] | None = None
) -> dict:
    if feature is None and before is not None:
        newest = _newest_feature_name(doc, before)
        if newest is not None:
            result = {"feature": newest}
            if name:
                _rename(newest, name)
                result["feature"] = name
            rebuild = inspect.rebuild(doc)
            if rebuild["ok"] and not rebuild["whats_wrong"]["count"]:
                return {
                    "data": result,
                    "evidence": {
                        "rebuild": rebuild,
                        "mass_properties": inspect.mass_properties(doc),
                    },
                }
    result = _require_feature_result(doc, feature, operation)
    if name:
        _rename(result["feature"], name)
        result["feature"] = name
    rebuild = inspect.rebuild(doc)
    evidence = {"rebuild": rebuild, "mass_properties": inspect.mass_properties(doc)}
    if not rebuild["ok"] or rebuild["whats_wrong"]["count"]:
        raise FeatureBuildError(
            f"{operation} built but the model reports errors",
            whats_wrong=rebuild["whats_wrong"],
            feature=result["feature"],
        )
    return {
        "data": result,
        "evidence": evidence,
    }


def _extrusion_arguments(
    depth_mm: float | None,
    end_condition: str,
    draft_deg: float,
    reverse: bool,
    both_directions: bool,
) -> list:
    code = END_CONDITIONS.get(end_condition)
    if code is None:
        raise InvalidParameterError(
            f"unknown end_condition {end_condition!r}",
            available=sorted(END_CONDITIONS),
        )
    if end_condition != "through_all_both" and depth_mm is None:
        raise InvalidParameterError(
            "depth_mm is required unless end_condition is through_all_both"
        )
    draft = units.deg_to_rad(draft_deg)
    if end_condition == "through_all_both":
        single, t1, t2, d1, d2 = False, 1, 1, 0.0, 0.0
    elif both_directions:
        single, t1, t2, d1, d2 = False, code, code, units.mm_to_m(depth_mm), units.mm_to_m(depth_mm)
    else:
        single, t1, t2, d1, d2 = True, code, 0, units.mm_to_m(depth_mm or 0), 0.0
    return [
        single,
        reverse,
        False,
        t1,
        t2,
        d1,
        d2,
        draft_deg != 0,
        False,
        False,
        False,
        draft,
        0.0,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        0,
        0.0,
        False,
    ]


def boss_extrude(
    depth_mm: float | None = None,
    end_condition: str = "blind",
    draft_deg: float = 0.0,
    reverse: bool = False,
    both_directions: bool = False,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    arguments = _extrusion_arguments(
        depth_mm, end_condition, draft_deg, reverse, both_directions
    )
    feature = doc.FeatureManager.FeatureExtrusion3(*arguments)
    return _finish_feature(doc, feature, "boss_extrude", name)


def _cut_arguments(
    depth_mm: float | None,
    end_condition: str,
    draft_deg: float,
    direction: bool,
    both_directions: bool,
    normal_cut: bool,
    flip_side: bool,
) -> list:
    values = _extrusion_arguments(
        depth_mm, end_condition, draft_deg, direction, both_directions
    )
    # For FeatureCut4 the second argument is "flip side to cut" (remove
    # everything outside the profile) and the third is the direction flag.
    # A single-ended cut with the direction flag unset builds nothing on this
    # build: the cut points into empty space.
    single, _flip, _dir, t1, t2, d1, d2, dr1, dr2, di1, di2, an1, an2 = values[:13]
    return [
        single,
        bool(flip_side),
        bool(direction),
        t1,
        t2,
        d1,
        d2,
        dr1,
        dr2,
        di1,
        di2,
        an1,
        an2,
        False,
        False,
        False,
        False,
        bool(normal_cut),
        True,
        True,
        False,
        False,
        False,
        0,
        0.0,
        False,
        True,
    ]


def cut_extrude(
    depth_mm: float | None = None,
    end_condition: str = "blind",
    draft_deg: float = 0.0,
    reverse: bool = False,
    both_directions: bool = False,
    normal_cut: bool = False,
    flip_side: bool = False,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    feature = doc.FeatureManager.FeatureCut4(
        *_cut_arguments(
            depth_mm,
            end_condition,
            draft_deg,
            reverse,
            both_directions,
            normal_cut,
            flip_side,
        )
    )
    reversed_automatically = False
    if (
        feature is None
        and not both_directions
        and end_condition != "through_all_both"
    ):
        # Which way the sketch plane faces is not predictable, and a cut that
        # removes nothing is unambiguous, so try the other direction.
        feature = doc.FeatureManager.FeatureCut4(
            *_cut_arguments(
                depth_mm,
                end_condition,
                draft_deg,
                not reverse,
                both_directions,
                normal_cut,
                flip_side,
            )
        )
        reversed_automatically = feature is not None
    result = _finish_feature(doc, feature, "cut_extrude", name)
    if reversed_automatically:
        result["data"]["reversed_automatically"] = True
    return result


def _select_sketch_centerline(doc) -> bool:
    feature = _last_feature(doc)
    if feature is None:
        return False
    try:
        sketch = binding.wrap(feature.GetSpecificFeature2(), "ISketch")
    except Exception:
        return False
    try:
        segments = sketch.GetSketchSegments() or []
    except Exception:
        return False
    data = inspect.create_select_data(doc)
    for raw in segments:
        segment = binding.wrap(raw, "ISketchSegment")
        try:
            if not binding.value(segment.ConstructionGeometry):
                continue
            if inspect.select_entity(segment, append=False, data=data):
                return True
        except Exception:
            continue
    return False


def revolve(
    angle_deg: float = 360.0,
    reverse: bool = False,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    used_centerline = _select_sketch_centerline(doc)
    feature = doc.FeatureManager.FeatureRevolve2(
        True,
        True,
        False,
        False,
        reverse,
        False,
        REVOLVE_BLIND,
        REVOLVE_BLIND,
        units.deg_to_rad(angle_deg),
        0.0,
        False,
        False,
        0.0,
        0.0,
        0,
        0.0,
        0.0,
        True,
        True,
        True,
    )
    result = _finish_feature(doc, feature, "revolve", name)
    result["data"]["axis"] = "selected_centerline" if used_centerline else "auto"
    return result


def fillet(
    radius_mm: float,
    edge_indices: list[int],
    propagate: bool = True,
    name: str | None = None,
) -> dict:
    if radius_mm <= 0:
        raise InvalidParameterError("radius_mm must be positive")
    _, doc, _ = session.active_doc(("part",))
    if not edge_indices:
        raise InvalidParameterError("edge_indices must not be empty")
    session.clear_selection(doc)
    inspect.select_edges(doc, edge_indices, append=False)
    options = 2 | (1 if propagate else 0)
    feature = doc.FeatureManager.FeatureFillet3(
        options,
        units.mm_to_m(radius_mm),
        0.0,
        0.0,
        0,
        0,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    return _finish_feature(doc, feature, "fillet", name)


def chamfer(
    distance_mm: float,
    edge_indices: list[int],
    angle_deg: float = 45.0,
    name: str | None = None,
) -> dict:
    if distance_mm <= 0:
        raise InvalidParameterError("distance_mm must be positive")
    _, doc, _ = session.active_doc(("part",))
    if not edge_indices:
        raise InvalidParameterError("edge_indices must not be empty")
    session.clear_selection(doc)
    inspect.select_edges(doc, edge_indices, append=False)
    feature = doc.FeatureManager.InsertFeatureChamfer(
        4,
        CHAMFER_EQUAL_DISTANCE,
        units.mm_to_m(distance_mm),
        units.deg_to_rad(angle_deg),
        0.0,
        0.0,
        0.0,
        0.0,
    )
    return _finish_feature(doc, feature, "chamfer", name)


def shell(
    thickness_mm: float,
    face_indices: list[int] | None = None,
    outward: bool = False,
    name: str | None = None,
) -> dict:
    if thickness_mm <= 0:
        raise InvalidParameterError("thickness_mm must be positive")
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    before = feature_names(doc)
    if face_indices:
        inspect.select_faces(doc, face_indices, append=False)
    feature = doc.InsertFeatureShell(units.mm_to_m(thickness_mm), bool(outward))
    return _finish_feature(doc, feature, "shell", name, before=before)


def _select_plane_or_face(
    doc,
    plane: str | None,
    face_index: int | None,
    mark: int,
    append: bool,
) -> str:
    if face_index is not None:
        inspect.select_faces(doc, [face_index], append=append, mark=mark)
        return f"face {face_index}"
    if plane is None:
        raise InvalidParameterError("pass a plane name or a planar face_index")
    return session.select_plane(doc, plane, mark=mark, append=append)


def _select_direction(
    doc,
    edge_index: int | None,
    plane: str | None,
    mark: int,
    append: bool,
) -> None:
    if edge_index is not None:
        inspect.select_edges(doc, [edge_index], append=append, mark=mark)
    elif plane is not None:
        session.select_plane(doc, plane, mark=mark, append=append)
    else:
        raise InvalidParameterError("pass an edge index or a plane name")


def _select_named_features(doc, feature_names: list[str], mark: int) -> None:
    for feature_name in feature_names:
        session.select_feature(doc, feature_name, append=True, mark=mark)


def create_reference_plane(
    kind: str = "offset",
    plane: str | None = None,
    face_index: int | None = None,
    second_plane: str | None = None,
    second_face_index: int | None = None,
    distance_mm: float | None = None,
    angle_deg: float | None = None,
    axis_edge: int | None = None,
    flip: bool = False,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    flip_bit = PLANE_CONSTRAINTS["flip"] if flip else 0
    if kind == "offset":
        if distance_mm is None:
            raise InvalidParameterError("kind=offset needs distance_mm")
        _select_plane_or_face(doc, plane, face_index, mark=0, append=False)
        constraints = (
            PLANE_CONSTRAINTS["distance"] | flip_bit,
            units.mm_to_m(distance_mm),
            0,
            0.0,
            0,
            0.0,
        )
    elif kind == "midplane":
        _select_plane_or_face(doc, plane, face_index, mark=0, append=False)
        _select_plane_or_face(
            doc, second_plane, second_face_index, mark=1, append=True
        )
        constraints = (
            PLANE_CONSTRAINTS["midplane"],
            0.0,
            PLANE_CONSTRAINTS["midplane"],
            0.0,
            0,
            0.0,
        )
    elif kind == "angle":
        if angle_deg is None or axis_edge is None:
            raise InvalidParameterError("kind=angle needs angle_deg and axis_edge")
        _select_plane_or_face(doc, plane, face_index, mark=0, append=False)
        inspect.select_edges(doc, [axis_edge], append=True, mark=1)
        constraints = (
            PLANE_CONSTRAINTS["angle"] | flip_bit,
            units.deg_to_rad(angle_deg),
            PLANE_CONSTRAINTS["coincident"],
            0.0,
            0,
            0.0,
        )
    else:
        raise InvalidParameterError(
            f"unknown kind {kind!r}", available=["offset", "midplane", "angle"]
        )
    before = feature_names(doc)
    # InsertRefPlane returns an untyped dispatch that does not QueryInterface
    # to IFeature, so the new plane is found by diffing the feature tree.
    doc.FeatureManager.InsertRefPlane(*constraints)
    result = _finish_feature(
        doc, None, "create_reference_plane", name, before=before
    )
    result["data"]["kind"] = kind
    result["data"]["planes"] = session.plane_names(doc)
    return result


def linear_pattern(
    feature_names_in: list[str],
    spacing_mm: float,
    direction_edge: int | None = None,
    direction_plane: str | None = None,
    count: int = 2,
    reverse: bool = False,
    direction2_edge: int | None = None,
    direction2_plane: str | None = None,
    spacing2_mm: float = 0.0,
    count2: int = 1,
    reverse2: bool = False,
    geometry_pattern: bool = False,
    name: str | None = None,
) -> dict:
    if not feature_names_in:
        raise InvalidParameterError("feature_names must not be empty")
    if spacing_mm <= 0:
        raise InvalidParameterError("spacing_mm must be positive")
    if count < 2:
        raise InvalidParameterError("count must be >= 2")
    has_second = direction2_edge is not None or direction2_plane is not None
    if has_second and (count2 < 2 or spacing2_mm <= 0):
        raise InvalidParameterError(
            "a second direction needs count2 >= 2 and spacing2_mm > 0"
        )
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    # FeatureLinearPattern5 reads the directions from marks 1/2 and the seed
    # features from mark 4; the direction names stay empty because the
    # references themselves are selected.
    _select_direction(doc, direction_edge, direction_plane, mark=1, append=False)
    if has_second:
        _select_direction(
            doc, direction2_edge, direction2_plane, mark=2, append=True
        )
    _select_named_features(doc, feature_names_in, mark=4)
    before = feature_names(doc)
    feature = doc.FeatureManager.FeatureLinearPattern5(
        int(count),
        units.mm_to_m(spacing_mm),
        int(count2) if has_second else 1,
        units.mm_to_m(spacing2_mm) if has_second else 0.0,
        bool(reverse),
        bool(reverse2),
        "",
        "",
        bool(geometry_pattern),
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        0.0,
        0.0,
        False,
        False,
    )
    return _finish_feature(doc, feature, "linear_pattern", name, before=before)


def circular_pattern(
    feature_names_in: list[str],
    count: int = 4,
    angle_deg: float = 360.0,
    axis_edge: int | None = None,
    axis_face: int | None = None,
    equal_spacing: bool = True,
    reverse: bool = False,
    geometry_pattern: bool = False,
    name: str | None = None,
) -> dict:
    if not feature_names_in:
        raise InvalidParameterError("feature_names must not be empty")
    if count < 2:
        raise InvalidParameterError("count must be >= 2")
    if (axis_edge is None) == (axis_face is None):
        raise InvalidParameterError(
            "pass exactly one of axis_edge (straight edge) or axis_face "
            "(cylindrical face)"
        )
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    # The axis is read from mark 1 and the seed features from mark 4.
    if axis_edge is not None:
        inspect.select_edges(doc, [axis_edge], append=False, mark=1)
    else:
        inspect.select_faces(doc, [axis_face], append=False, mark=1)
    _select_named_features(doc, feature_names_in, mark=4)
    before = feature_names(doc)
    feature = doc.FeatureManager.FeatureCircularPattern5(
        int(count),
        units.deg_to_rad(angle_deg),
        bool(reverse),
        "",
        bool(geometry_pattern),
        bool(equal_spacing),
        False,
        False,
        False,
        False,
        1,
        0.0,
        "",
        False,
    )
    return _finish_feature(doc, feature, "circular_pattern", name, before=before)


def mirror_feature(
    feature_names_in: list[str],
    plane: str | None = None,
    face_index: int | None = None,
    mirror_body: bool = False,
    geometry_pattern: bool = False,
    merge: bool = True,
    name: str | None = None,
) -> dict:
    if not feature_names_in:
        raise InvalidParameterError("feature_names must not be empty")
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    # InsertMirrorFeature2 reads the mirror plane from mark 2 and the features
    # being mirrored from mark 1.
    _select_plane_or_face(doc, plane, face_index, mark=2, append=False)
    _select_named_features(doc, feature_names_in, mark=1)
    before = feature_names(doc)
    feature = doc.FeatureManager.InsertMirrorFeature2(
        bool(mirror_body), bool(geometry_pattern), bool(merge), False, 0
    )
    return _finish_feature(doc, feature, "mirror_feature", name, before=before)


def rename_feature(current_name: str, new_name: str) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    for feature in session.iter_features(doc):
        if str(binding.value(feature.Name)) == current_name:
            feature.Name = new_name
            return {"renamed": current_name, "to": new_name}
    raise SelectionError(f"feature {current_name!r} not found")


def delete_feature(name: str, absorb_children: bool = False) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    session.clear_selection(doc)
    session.select_feature(doc, name)
    ok = doc.Extension.DeleteSelection2(2 if absorb_children else 1)
    if not ok:
        raise ComCallError(
            f"SOLIDWORKS refused to delete {name!r}",
            hint="Child features may depend on it; try absorb_children=true.",
        )
    return {"deleted": name}


def set_material(name: str, database: str = "SOLIDWORKS Materials") -> dict:
    _, doc, _ = session.active_doc(("part",))
    part = binding.wrap(doc, "IPartDoc")
    part.SetMaterialPropertyName(database, name)
    evidence = {"mass_properties": inspect.mass_properties(doc)}
    density = evidence["mass_properties"].get("density_kg_m3")
    return {
        "data": {"material": name, "database": database, "density_kg_m3": density},
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Holes, sweep, loft and draft
# ---------------------------------------------------------------------------

def face_objects(doc, body_type: str = "all") -> list:
    faces = []
    for body in inspect._bodies(doc, body_type):
        faces.extend(inspect._faces(body))
    return faces


def face_point_from_offsets(face, x_mm: float, y_mm: float) -> list[float]:
    """Map in-face offsets to a model point on an axis-aligned planar face.

    x_mm runs along the face's first in-plane model axis (X before Y before
    Z), y_mm along the second; both are measured from the face's minimum
    corner. This is the point ISelectData carries into SimpleHole2, the
    official way to locate a hole; a positioning sketch is not needed.
    """
    box = [float(value) for value in binding.value(face.GetBox())]
    if len(box) < 6:
        raise ComCallError("the face has no bounding box")
    normal = binding.value(face.Normal)
    unit = [round(float(value)) for value in normal[:3]]
    axes = [index for index in range(3) if abs(unit[index]) != 1]
    if len(axes) != 2:
        raise SelectionError(
            "simple_hole needs a planar face aligned with a base axis",
            hint="Use a face from an axis-aligned extrusion.",
        )
    point = [0.0, 0.0, 0.0]
    point[axes[0]] = box[axes[0]] + units.mm_to_m(x_mm)
    point[axes[1]] = box[axes[1]] + units.mm_to_m(y_mm)
    normal_axis = 3 - axes[0] - axes[1]
    point[normal_axis] = (box[normal_axis] + box[normal_axis + 3]) / 2.0
    for axis in axes:
        if not box[axis] - 1e-9 <= point[axis] <= box[axis + 3] + 1e-9:
            raise InvalidParameterError(
                "the hole position falls outside the face",
                hint="x_mm/y_mm are measured from the face's minimum corner.",
            )
    return point


def simple_hole(
    diameter_mm: float,
    face_index: int,
    x_mm: float,
    y_mm: float,
    depth_mm: float = 10.0,
    end_condition: str = "blind",
    reverse: bool = False,
    name: str | None = None,
) -> dict:
    """Drill a straight hole located by a point on an axis-aligned face."""
    if diameter_mm <= 0:
        raise InvalidParameterError("diameter_mm must be positive")
    code = END_CONDITIONS.get(end_condition)
    if code is None:
        raise InvalidParameterError(
            f"unknown end_condition {end_condition!r}",
            available=sorted(END_CONDITIONS),
        )
    if end_condition == "through_all_both":
        raise InvalidParameterError(
            "a hole cannot be through_all_both; use through_all"
        )
    _, doc, _ = session.active_doc(("part",))
    faces = face_objects(doc)
    if not isinstance(face_index, int) or not 0 <= face_index < len(faces):
        raise SelectionError(
            f"face index {face_index} out of range (0..{len(faces) - 1})"
        )
    face = faces[face_index]
    point = face_point_from_offsets(face, x_mm, y_mm)
    session.clear_selection(doc)
    # The official SimpleHole2 pattern selects the face with an ISelectData
    # whose X/Y/Z carry the hole location; no positioning sketch is involved.
    data = inspect.create_select_data(doc)
    if data is None:
        raise ComCallError("could not create selection data")
    data.X, data.Y, data.Z = point
    if not inspect.select_entity(face, append=False, mark=0, data=data):
        raise SelectionError(f"could not select face {face_index}")
    before = feature_names(doc)
    feature = doc.FeatureManager.SimpleHole2(
        units.mm_to_m(diameter_mm),
        True,
        False,
        bool(reverse),
        code,
        0,
        units.mm_to_m(depth_mm),
        0.0,
        False,
        False,
        False,
        False,
        0.0,
        0.0,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
    )
    result = _finish_feature(doc, feature, "simple_hole", name, before=before)
    result["data"]["diameter_mm"] = diameter_mm
    result["data"]["face_index"] = face_index
    result["data"]["position_mm"] = [
        round(units.m_to_mm(value), 4) for value in point
    ]
    return result


def draft(
    angle_deg: float,
    face_indices: list[int],
    neutral_face_index: int | None = None,
    neutral_plane: str | None = None,
    reverse: bool = False,
    name: str | None = None,
) -> dict:
    if not face_indices:
        raise InvalidParameterError("face_indices must not be empty")
    if (neutral_face_index is None) == (neutral_plane is None):
        raise InvalidParameterError(
            "pass exactly one of neutral_face_index or neutral_plane"
        )
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    # InsertMultiFaceDraft reads the neutral reference from mark 1 and the
    # drafted faces from mark 2 (measured; the docs are silent on the marks).
    _select_plane_or_face(
        doc, neutral_plane, neutral_face_index, mark=1, append=False
    )
    inspect.select_faces(doc, face_indices, append=True, mark=2)
    before = feature_names(doc)
    feature = doc.FeatureManager.InsertMultiFaceDraft(
        units.deg_to_rad(angle_deg), bool(reverse), False, 0, False, False
    )
    result = _finish_feature(doc, feature, "draft", name, before=before)
    result["data"]["angle_deg"] = angle_deg
    result["data"]["faces"] = len(face_indices)
    return result


def sweep(
    profile_sketch: str,
    path_sketch: str,
    cut: bool = False,
    merge: bool = True,
    keep_tangency: bool = False,
    twist_angle_deg: float = 0.0,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    # The sweep APIs read the profile from mark 1 and the path from mark 4.
    session.select_sketch(doc, profile_sketch, append=False, mark=1)
    session.select_sketch(doc, path_sketch, append=True, mark=4)
    before = feature_names(doc)
    twist = units.deg_to_rad(twist_angle_deg)
    if cut:
        feature = doc.FeatureManager.InsertCutSwept5(
            False, True, 0, bool(keep_tangency), False,
            0, 0, False, 0.0, 0.0, 0, 0,
            True, True, twist, False,
            False, False, False, False,
            0.0, 0,
        )
    else:
        feature = doc.FeatureManager.InsertProtrusionSwept4(
            False, True, 0, bool(keep_tangency), False,
            0, 0, False, 0.0, 0.0, 0, 0,
            bool(merge), True, True, twist, False, False, 0.0, 0,
        )
    result = _finish_feature(doc, feature, "sweep", name, before=before)
    result["data"]["profile"] = profile_sketch
    result["data"]["path"] = path_sketch
    return result


def loft(
    profile_sketches: list[str],
    cut: bool = False,
    closed: bool = False,
    keep_tangency: bool = False,
    merge: bool = True,
    name: str | None = None,
) -> dict:
    if len(profile_sketches) < 2:
        raise InvalidParameterError("a loft needs at least two profile sketches")
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    # Loft reads every profile from mark 1; order is the selection order.
    for index, sketch_name in enumerate(profile_sketches):
        session.select_sketch(doc, sketch_name, append=index > 0, mark=1)
    before = feature_names(doc)
    if cut:
        feature = doc.FeatureManager.InsertCutBlend(
            bool(closed), bool(keep_tangency), False, 1.0,
            0, 0, False, 0.0, 0.0, 0, True, True,
        )
    else:
        feature = doc.FeatureManager.InsertProtrusionBlend2(
            bool(closed), bool(keep_tangency), False, 1.0,
            0, 0, 0.0, 0.0, True, True, False, 0.0, 0.0,
            0, bool(merge), True, True, 0,
        )
    result = _finish_feature(doc, feature, "loft", name, before=before)
    result["data"]["profiles"] = list(profile_sketches)
    return result


def set_feature_suppression(
    feature_names_in: list[str], suppressed: bool = True
) -> dict:
    if not feature_names_in:
        raise InvalidParameterError("feature_names must not be empty")
    _, doc, kind = session.active_doc(("part", "assembly", "drawing"))
    for feature_name in feature_names_in:
        session.clear_selection(doc)
        session.select_feature(doc, feature_name)
        if suppressed:
            doc.EditSuppress2()
        else:
            doc.EditUnsuppress2()
    session.clear_selection(doc)
    states = []
    for feature_name in feature_names_in:
        state = None
        for feature in session.iter_features(doc):
            if str(binding.value(feature.Name)) != feature_name:
                continue
            try:
                state = bool(binding.value(feature.IsSuppressed))
            except Exception:
                state = None
            break
        states.append({"feature": feature_name, "suppressed": state})
    if any(
        item["suppressed"] is not None and item["suppressed"] != bool(suppressed)
        for item in states
    ):
        raise ComCallError(
            "SOLIDWORKS did not change the suppression state",
            states=states,
        )
    rebuild = inspect.rebuild(doc)
    evidence: dict = {"rebuild": rebuild}
    if kind == "part":
        evidence["mass_properties"] = inspect.mass_properties(doc)
    return {
        "data": {"suppressed": bool(suppressed), "features": states},
        "evidence": evidence,
    }


def create_axis(
    face_index: int | None = None,
    edge_index: int | None = None,
    planes: list[str] | None = None,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    if planes:
        for index, plane in enumerate(planes):
            session.select_plane(doc, plane, append=index > 0)
    elif edge_index is not None:
        inspect.select_edges(doc, [edge_index], append=False)
    elif face_index is not None:
        inspect.select_faces(doc, [face_index], append=False)
    else:
        raise InvalidParameterError("pass face_index, edge_index or planes")
    before = feature_names(doc)
    if not bool(doc.InsertAxis2(True)):
        raise ComCallError(
            "SOLIDWORKS could not build an axis from that selection",
            hint="Use a cylindrical face, a straight edge, two planes or "
            "two points.",
        )
    result = _finish_feature(doc, None, "create_axis", name, before=before)
    result["data"]["axes"] = session.axis_names(doc)
    return result


def list_reference_planes() -> dict:
    _, doc, _ = session.active_doc(("part",))
    return {"planes": session.plane_names(doc), "axes": session.axis_names(doc)}
