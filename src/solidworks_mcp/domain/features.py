"""Solid features: extrude, cut, revolve, fillet, chamfer, shell, material."""
from __future__ import annotations

import math
from ..com import binding, units
from ..errors import (
    ComCallError,
    FeatureBuildError,
    InvalidParameterError,
    SelectionError,
)
from . import inspect, references, session

END_CONDITIONS = {
    "blind": 0,
    "through_all": 1,
    "up_to_vertex": 3,
    "up_to_surface": 4,
    "offset_from_surface": 5,
    "mid_plane": 6,
    "up_to_body": 7,
    "through_all_both": 9,
    "up_to_next": 11,
}
# End conditions that need a reference (plane/face, vertex or body) selected
# together with the profile sketch.
REFERENCE_END_CONDITIONS = (
    "up_to_surface",
    "offset_from_surface",
    "up_to_vertex",
    "up_to_body",
)
REVOLVE_BLIND = 0
# Measured on SW2026 SP0.0: type 1 is angle-distance (Width along the face,
# Angle from it; 45 degrees renders an equal-distance chamfer). The typelib's
# "EqualDistance = 16" builds a feature that removes nothing in every tested
# parameter set, so it is not used.
CHAMFER_TYPES = {"angle_distance": 1, "distance_distance": 2}
CHAMFER_EQUAL_ANGLE_DEG = 45.0
# RevThinDir: 0 puts the wall outside the profile, 1 inside, 2 centred
# (measured: ring removals 2638.94 / 2387.61 / 2513.27 mm3 for r=20, t=2).
THIN_SIDES = {"outward": 0, "inward": 1, "mid": 2}

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


def _rename(feature_name: str, new_name: str | None, doc=None) -> None:
    if not new_name:
        return
    if doc is None:
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
                _rename(newest, name, doc=doc)
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
        _rename(result["feature"], name, doc=doc)
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
    offset_mm: float | None = None,
    merge: bool = True,
) -> list:
    code = END_CONDITIONS.get(end_condition)
    if code is None:
        raise InvalidParameterError(
            f"unknown end_condition {end_condition!r}",
            available=sorted(END_CONDITIONS),
        )
    if end_condition in ("blind", "up_to_next", "mid_plane") and depth_mm is None:
        raise InvalidParameterError(
            f"depth_mm is required for end_condition {end_condition!r}"
        )
    if end_condition == "offset_from_surface" and offset_mm is None:
        raise InvalidParameterError(
            "offset_from_surface needs offset_mm (mm); a negative value pulls "
            "the end back toward the sketch"
        )
    if both_directions and end_condition != "blind":
        raise InvalidParameterError(
            "both_directions is only available with the blind end condition"
        )
    draft = units.deg_to_rad(draft_deg)
    if end_condition == "through_all_both":
        single, t1, t2, d1, d2 = False, 1, 1, 0.0, 0.0
    elif both_directions:
        single, t1, t2, d1, d2 = (
            False,
            code,
            code,
            units.mm_to_m(depth_mm),
            units.mm_to_m(depth_mm),
        )
    else:
        single, t1, t2 = True, code, 0
        if end_condition == "offset_from_surface":
            d1 = units.mm_to_m(abs(offset_mm))
        else:
            d1 = units.mm_to_m(depth_mm or 0)
        d2 = 0.0
    # Measured on SW2026 SP0.0: OffsetReverse=True extends past the reference
    # surface (plane at 30 + offset 5 -> top at 35); False cuts back (25).
    # Positive offset_mm means "beyond the reference", negative pulls back.
    offset_reverse = bool(offset_mm is not None and offset_mm > 0)
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
        offset_reverse,
        False,
        False,
        False,
        bool(merge),
        True,
        True,
        0,
        0.0,
        False,
    ]


def _select_extrude_reference(
    doc,
    end_condition: str,
    plane: str | None,
    face_index: int | None,
    body_index: int | None,
    vertex_index: int | None,
) -> str:
    """Select the profile sketch (mark 0) and the end-condition reference.

    Measured on SW2026 SP0.0: the profile must be in mark 0 and the reference
    in mark 1; a reference in mark 0 throws from ``FeatureExtrusion3``, and
    no selection at all returns None silently.
    """
    names = session.sketch_names(doc)
    if not names:
        raise SelectionError(
            "no sketch to extrude; create a sketch and close it first"
        )
    session.select_sketch(doc, names[-1], append=False, mark=0)
    if end_condition in ("up_to_surface", "offset_from_surface"):
        if face_index is not None:
            inspect.select_faces(doc, [face_index], append=True, mark=1)
            return f"face {face_index}"
        if plane:
            return session.select_plane(doc, plane, mark=1, append=True)
        raise InvalidParameterError(
            f"{end_condition} needs a plane name or a face_index reference"
        )
    if end_condition == "up_to_vertex":
        if vertex_index is None:
            raise InvalidParameterError("up_to_vertex needs vertex_index")
        inspect.select_vertices(doc, [vertex_index], append=True, mark=1)
        return f"vertex {vertex_index}"
    if end_condition == "up_to_body":
        if body_index is None:
            raise InvalidParameterError("up_to_body needs body_index")
        inspect.select_bodies(doc, [body_index], append=True, mark=1)
        return f"body {body_index}"
    return ""


def boss_extrude(
    depth_mm: float | None = None,
    end_condition: str = "blind",
    draft_deg: float = 0.0,
    reverse: bool = False,
    both_directions: bool = False,
    name: str | None = None,
    offset_mm: float | None = None,
    plane: str | None = None,
    face_index: int | None = None,
    body_index: int | None = None,
    vertex_index: int | None = None,
    merge: bool = True,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    reference = None
    if end_condition in REFERENCE_END_CONDITIONS:
        # Only the reference path manages the selection: the plain path must
        # keep whatever the "just-closed sketch" left selected, because
        # FeatureExtrusion3 reads the profile from the selection set.
        session.clear_selection(doc)
        reference = _select_extrude_reference(
            doc, end_condition, plane, face_index, body_index, vertex_index
        )
    arguments = _extrusion_arguments(
        depth_mm, end_condition, draft_deg, reverse, both_directions,
        offset_mm, merge,
    )
    before = feature_names(doc)
    feature = doc.FeatureManager.FeatureExtrusion3(*arguments)
    result = _finish_feature(doc, feature, "boss_extrude", name, before=before)
    result["data"]["end_condition"] = end_condition
    if reference:
        result["data"]["reference"] = reference
    return result


def _cut_arguments(
    depth_mm: float | None,
    end_condition: str,
    draft_deg: float,
    direction: bool,
    both_directions: bool,
    normal_cut: bool,
    flip_side: bool,
    offset_mm: float | None = None,
) -> list:
    values = _extrusion_arguments(
        depth_mm, end_condition, draft_deg, direction, both_directions, offset_mm
    )
    # For FeatureCut4 the second argument is "flip side to cut" (remove
    # everything outside the profile) and the third is the direction flag.
    # A single-ended cut with the direction flag unset builds nothing on this
    # build: the cut points into empty space.
    (
        single, _flip, _dir, t1, t2, d1, d2, dr1, dr2, di1, di2, an1, an2,
        offset_reverse, _offset_reverse2, ts1, ts2,
    ) = values[:17]
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
        offset_reverse,
        False,
        ts1,
        ts2,
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
    offset_mm: float | None = None,
    plane: str | None = None,
    face_index: int | None = None,
    body_index: int | None = None,
    vertex_index: int | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    reference = None
    if end_condition in REFERENCE_END_CONDITIONS:
        # Selection is only managed on the reference path; a plain cut reads
        # the profile from the selection the closed sketch left behind.
        session.clear_selection(doc)
        reference = _select_extrude_reference(
            doc, end_condition, plane, face_index, body_index, vertex_index
        )
    before = feature_names(doc)
    feature = doc.FeatureManager.FeatureCut4(
        *_cut_arguments(
            depth_mm,
            end_condition,
            draft_deg,
            reverse,
            both_directions,
            normal_cut,
            flip_side,
            offset_mm,
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
        if end_condition in REFERENCE_END_CONDITIONS:
            session.clear_selection(doc)
            reference = _select_extrude_reference(
                doc, end_condition, plane, face_index, body_index, vertex_index
            )
        feature = doc.FeatureManager.FeatureCut4(
            *_cut_arguments(
                depth_mm,
                end_condition,
                draft_deg,
                not reverse,
                both_directions,
                normal_cut,
                flip_side,
                offset_mm,
            )
        )
        reversed_automatically = feature is not None
    result = _finish_feature(doc, feature, "cut_extrude", name, before=before)
    result["data"]["end_condition"] = end_condition
    if reference:
        result["data"]["reference"] = reference
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


def revolve_cut(
    angle_deg: float = 360.0,
    reverse: bool = False,
    name: str | None = None,
) -> dict:
    """Revolve-cut the sketch shown on screen around its centerline.

    ``FeatureRevolveCut2`` takes the angle first (unlike ``FeatureRevolve2``);
    the axis comes from the newest sketch's construction geometry, same as
    ``revolve``.
    """
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    used_centerline = _select_sketch_centerline(doc)
    feature = doc.FeatureManager.FeatureRevolveCut2(
        units.deg_to_rad(angle_deg),
        bool(reverse),
        0.0,
        REVOLVE_BLIND,
        0,
        False,
        False,
        False,
        False,
        False,
    )
    result = _finish_feature(doc, feature, "revolve_cut", name)
    result["data"]["axis"] = "selected_centerline" if used_centerline else "auto"
    return result


def _thin_common(
    t1: int,
    depth_mm: float | None,
    thickness_mm: float,
    side_code: int,
    reverse: bool,
) -> list:
    """The 24 arguments shared by FeatureCutThin2 and FeatureBossThin2."""
    return [
        True,  # Sd
        bool(reverse),  # Flip
        True,  # Dir (measured working value for both thin APIs)
        t1,
        0,  # T2
        units.mm_to_m(depth_mm or 0.0),
        0.0,  # D2
        False,
        False,
        False,
        False,
        0.0,
        0.0,
        False,  # OffsetReverse1
        False,  # OffsetReverse2
        False,  # TranslateSurface1
        False,  # TranslateSurface2
        units.mm_to_m(thickness_mm),
        0.0,  # Thk2
        0.0,  # EndThk
        int(side_code),  # RevThinDir
        0,  # CapEnds
        False,  # AddBends
        0.0,  # BendRad
    ]


def thin_extrude(
    depth_mm: float | None = None,
    end_condition: str = "blind",
    thickness_mm: float = 1.0,
    side: str = "mid",
    cut: bool = False,
    reverse: bool = False,
    name: str | None = None,
) -> dict:
    """Thin-wall extrude: an open profile swept as a wall of ``thickness_mm``.

    Measured on SW2026 SP0.0: ``side`` maps to RevThinDir outward=0,
    inward=1, mid=2; a through-all thin cut builds with the direction flag
    set. The boss form (``IFeatureBossThin2``) returns void, so it is judged
    by the feature-tree diff.
    """
    if thickness_mm <= 0:
        raise InvalidParameterError("thickness_mm must be positive")
    side_code = THIN_SIDES.get(side)
    if side_code is None:
        raise InvalidParameterError(
            f"unknown side {side!r}", available=sorted(THIN_SIDES)
        )
    code = END_CONDITIONS.get(end_condition)
    if code is None:
        raise InvalidParameterError(
            f"unknown end_condition {end_condition!r}",
            available=sorted(END_CONDITIONS),
        )
    if end_condition not in ("blind", "through_all"):
        raise InvalidParameterError(
            "a thin feature supports blind and through_all only",
            available=["blind", "through_all"],
        )
    if end_condition == "blind" and depth_mm is None:
        raise InvalidParameterError("depth_mm is required for a blind thin feature")
    _, doc, _ = session.active_doc(("part",))
    # Keep the just-closed sketch selected. FeatureCutThin2 and
    # FeatureBossThin2 read the profile from that selection, like the normal
    # extrusion path; clearing it makes both APIs return no feature.
    before = feature_names(doc)
    common = _thin_common(code, depth_mm, thickness_mm, side_code, reverse)
    if cut:
        # The cut direction flag must be set (the same measured trap as
        # FeatureCut4); if the requested side removes nothing, flip it.
        arguments = common[:]
        arguments[2] = True
        feature = doc.FeatureManager.FeatureCutThin2(
            *arguments, True, True, 0, 0.0, False
        )
        if feature is None and not before.intersection(feature_names(doc)):
            arguments = _thin_common(
                code, depth_mm, thickness_mm, side_code, not reverse
            )
            arguments[2] = True
            feature = doc.FeatureManager.FeatureCutThin2(
                *arguments, True, True, 0, 0.0, False
            )
        result = _finish_feature(doc, feature, "thin_extrude", name, before=before)
    else:
        doc.FeatureBossThin2(*common)
        result = _finish_feature(doc, None, "thin_extrude", name, before=before)
    result["data"].update(
        {
            "thickness_mm": thickness_mm,
            "side": side,
            "cut": bool(cut),
            "end_condition": end_condition,
        }
    )
    return result


def fillet(
    radius_mm: float,
    edge_indices: list[int] | None = None,
    propagate: bool = True,
    name: str | None = None,
    kind: str = "constant",
    face_indices: list[int] | None = None,
) -> dict:
    """Round edges (constant radius) or blend between two faces.

    ``kind="face"`` takes exactly two faces in ``face_indices`` (they meet at
    the edge to blend); measured on SW2026 SP0.0 the two faces are selected
    with plain mark 0, Ftyp=2. Variable-radius and asymmetric fillets are
    measured-unreliable on this build (see docs/COM-QUIRKS.md) and are not
    exposed.
    """
    if radius_mm <= 0:
        raise InvalidParameterError("radius_mm must be positive")
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    if kind == "constant":
        if not edge_indices:
            raise InvalidParameterError("edge_indices must not be empty")
        inspect.select_edges(doc, edge_indices, append=False)
        ftyp = 0
    elif kind == "face":
        if not face_indices or len(face_indices) != 2:
            raise InvalidParameterError(
                "kind=face needs exactly two face_indices (from list_faces)"
            )
        inspect.select_faces(doc, face_indices, append=False)
        ftyp = 2  # swFeatureFilletType_Face
    else:
        raise InvalidParameterError(
            f"unknown fillet kind {kind!r}", available=["constant", "face"]
        )
    options = 2 | (1 if propagate else 0)
    feature = doc.FeatureManager.FeatureFillet3(
        options,
        units.mm_to_m(radius_mm),
        0.0,
        0.0,
        ftyp,
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
    result = _finish_feature(doc, feature, "fillet", name)
    result["data"]["kind"] = kind
    return result


def _chamfer_arguments(
    kind: str, angle_deg: float, second_distance_mm: float | None
) -> tuple[int, float, float]:
    """Map a tool-level chamfer kind to (Type, Angle, OtherDist)."""
    if kind == "equal":
        return CHAMFER_TYPES["angle_distance"], CHAMFER_EQUAL_ANGLE_DEG, 0.0
    if kind == "angle_distance":
        return CHAMFER_TYPES["angle_distance"], angle_deg, 0.0
    if kind == "distance_distance":
        if second_distance_mm is None or second_distance_mm <= 0:
            raise InvalidParameterError(
                "kind=distance_distance needs a positive second_distance_mm"
            )
        return CHAMFER_TYPES["distance_distance"], 0.0, second_distance_mm
    raise InvalidParameterError(
        f"unknown chamfer kind {kind!r}",
        available=["equal", "angle_distance", "distance_distance"],
    )


def chamfer(
    distance_mm: float,
    edge_indices: list[int],
    angle_deg: float = CHAMFER_EQUAL_ANGLE_DEG,
    name: str | None = None,
    kind: str = "equal",
    second_distance_mm: float | None = None,
) -> dict:
    """Chamfer edges.

    Measured on SW2026 SP0.0: ``InsertFeatureChamfer`` type 1 is
    angle-distance with ``distance_mm`` along the first face and ``angle_deg``
    from it, so ``kind="equal"`` is type 1 at 45 degrees. Type 2 is
    distance-distance (``distance_mm`` + ``second_distance_mm``). The
    typelib's EqualDistance=16 builds a feature that removes nothing.
    """
    if distance_mm <= 0:
        raise InvalidParameterError("distance_mm must be positive")
    if not edge_indices:
        raise InvalidParameterError("edge_indices must not be empty")
    ctype, angle, other = _chamfer_arguments(kind, angle_deg, second_distance_mm)
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    inspect.select_edges(doc, edge_indices, append=False)
    feature = doc.FeatureManager.InsertFeatureChamfer(
        4,
        ctype,
        units.mm_to_m(distance_mm),
        units.deg_to_rad(angle),
        units.mm_to_m(other),
        0.0,
        0.0,
        0.0,
    )
    result = _finish_feature(doc, feature, "chamfer", name)
    result["data"]["kind"] = kind
    return result


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
    entity_ref: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    if entity_ref is not None:
        if (kind != "offset" or plane is not None or face_index is not None
                or second_plane is not None or second_face_index is not None
                or axis_edge is not None or angle_deg is not None or flip):
            raise InvalidParameterError("entity_ref accepts only the fixed face-offset workflow")
        if (not isinstance(distance_mm, (int, float)) or not math.isfinite(distance_mm)
                or distance_mm == 0 or not isinstance(name, str) or not 1 <= len(name) <= 64):
            raise InvalidParameterError("face offset needs a finite nonzero distance and a bounded name")
        references.resolve_offset_face(doc, entity_ref)
        if name in feature_names(doc):
            raise InvalidParameterError("the requested feature name already exists")
    session.clear_selection(doc)
    flip_bit = PLANE_CONSTRAINTS["flip"] if flip else 0
    if kind == "offset":
        if distance_mm is None:
            raise InvalidParameterError("kind=offset needs distance_mm")
        if entity_ref is not None:
            # Re-resolve inside this same STA mutation job, immediately before
            # selecting the reference used by InsertRefPlane. Never reuse a read index.
            target = references.resolve_offset_face(doc, entity_ref)
            data = inspect.create_select_data(doc, 0)
            if not inspect.select_entity(target["entity"], False, mark=0, data=data):
                raise SelectionError("could not select the revalidated planar face")
        else:
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
    try:
        raw_triangles = binding.value(face.GetTessTriangles(True))
        triangles = [float(value) for value in raw_triangles or []]
    except Exception as exc:
        raise ComCallError(
            "could not validate the hole position against the trimmed face"
        ) from exc
    if len(triangles) < 9 or len(triangles) % 9:
        raise ComCallError(
            "the face did not provide a usable tessellation for point validation"
        )
    projected = [point[axes[0]], point[axes[1]]]
    inside = False
    for offset in range(0, len(triangles) - 8, 9):
        vertices = [
            [triangles[offset + vertex * 3 + axis] for axis in axes]
            for vertex in range(3)
        ]
        if _point_in_triangle_2d(projected, vertices, tolerance=1e-8):
            inside = True
            break
    if not inside:
        raise InvalidParameterError(
            "the hole position lies outside the trimmed face",
            hint=(
                "Offsets use ascending model axes from the face bounding-box "
                "minimum; avoid holes, slots, and trimmed-out regions."
            ),
        )
    return point


def _point_in_triangle_2d(point, vertices, tolerance: float = 1e-9) -> bool:
    """Test a projected point against one tessellated planar-face triangle."""
    a, b, c = vertices
    px, py = point
    ax, ay = a
    bx, by = b
    cx, cy = c
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(area) <= tolerance * tolerance:
        return False
    first = ((px - ax) * (cy - ay) - (py - ay) * (cx - ax)) / area
    second = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / area
    third = 1.0 - first - second
    return min(first, second, third) >= -tolerance


def _resolve_hole_face(doc, face_index: int, x_mm: float, y_mm: float):
    faces = face_objects(doc)
    if not isinstance(face_index, int) or not 0 <= face_index < len(faces):
        raise SelectionError(
            f"face index {face_index} out of range (0..{len(faces) - 1})"
        )
    face = faces[face_index]
    point = face_point_from_offsets(face, x_mm, y_mm)
    return face, point


def _planar_face_signature(face) -> dict:
    box = [float(value) for value in binding.value(face.GetBox())]
    normal = [float(value) for value in binding.value(face.Normal)[:3]]
    normal_axis = max(range(3), key=lambda axis: abs(normal[axis]))
    if abs(normal[normal_axis]) < 0.999:
        raise SelectionError("compound holes require an axis-aligned planar face")
    return {
        "box": box,
        "normal": normal,
        "normal_axis": normal_axis,
        "plane": (box[normal_axis] + box[normal_axis + 3]) / 2.0,
    }


def _refresh_hole_face(doc, signature: dict, point: list[float]):
    """Resolve the same planar support face after the pilot cut rebuilds topology."""
    matches = []
    for face in face_objects(doc):
        try:
            surface = binding.wrap(face.GetSurface(), "ISurface")
            if not bool(binding.value(surface.IsPlane)):
                continue
            candidate = _planar_face_signature(face)
        except Exception:
            continue
        axis = signature["normal_axis"]
        if abs(candidate["plane"] - signature["plane"]) > 1e-7:
            continue
        if sum(
            candidate["normal"][i] * signature["normal"][i] for i in range(3)
        ) < 0.999:
            continue
        if any(
            not candidate["box"][i] - 1e-8 <= point[i] <= candidate["box"][i + 3] + 1e-8
            for i in range(3) if i != axis
        ):
            continue
        box_error = sum(
            (candidate["box"][i] - signature["box"][i]) ** 2
            for i in range(6)
        )
        try:
            area = float(face.GetArea())
        except Exception:
            area = 0.0
        matches.append((box_error, -area, face))
    if not matches:
        raise SelectionError(
            "could not re-resolve the counterbore face after the pilot cut"
        )
    matches.sort(key=lambda value: (value[0], value[1]))
    if len(matches) > 1 and all(
        abs(matches[index][0] - matches[0][0]) <= 1e-14
        and abs(matches[index][1] - matches[0][1]) <= 1e-9
        for index in (1,)
    ):
        raise SelectionError(
            "the counterbore support face is ambiguous after the pilot cut"
        )
    return matches[0][2]


def _model_fingerprint(doc) -> dict:
    return {
        "features": feature_names(doc),
        "mass": inspect.mass_properties(doc, "maximum"),
        "bounds": inspect.bounding_box(doc),
        "topology": [
            (len(inspect._faces(body)), len(inspect._edges(body)))
            for body in inspect._bodies(doc, "solid")
        ],
    }


def _rollback_features(doc, original_names: set[str]) -> None:
    created = [
        str(binding.value(feature.Name)) for feature in session.iter_features(doc)
        if str(binding.value(feature.Name)) not in original_names
    ]
    for name in reversed(created):
        if name not in feature_names(doc):
            continue
        session.clear_selection(doc)
        session.select_feature(doc, name)
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
        if not extension.DeleteSelection2(1):
            raise ComCallError(f"could not roll back feature {name!r}")
    session.clear_selection(doc)
    rebuilt = inspect.rebuild(doc)
    if not rebuilt.get("ok") or rebuilt.get("whats_wrong", {}).get("count", 0):
        raise ComCallError("the model did not rebuild cleanly after rollback")


def _same_fingerprint(before: dict, after: dict) -> bool:
    if before["features"] != after["features"] or before["topology"] != after["topology"]:
        return False
    for key in ("volume_mm3", "area_mm2", "mass_g"):
        if not math.isclose(
            before["mass"].get(key, float("nan")),
            after["mass"].get(key, float("nan")),
            rel_tol=1e-10,
            abs_tol=1e-7,
        ):
            return False
    for key in ("min_mm", "max_mm"):
        if any(
            abs(float(a) - float(b)) > 1e-6
            for a, b in zip(before["bounds"][key], after["bounds"][key])
        ):
            return False
    return True


def _simple_hole_feature(
    doc,
    face,
    point,
    diameter_mm: float,
    code: int,
    depth_mm: float | None,
    reverse: bool = False,
):
    """One SimpleHole2 drilling into ``face`` at ``point`` (metres)."""
    session.clear_selection(doc)
    # The official SimpleHole2 pattern selects the face with an ISelectData
    # whose X/Y/Z carry the hole location; no positioning sketch is involved.
    data = inspect.create_select_data(doc)
    if data is None:
        raise ComCallError("could not create selection data")
    data.X, data.Y, data.Z = point
    if not inspect.select_entity(face, append=False, mark=0, data=data):
        raise SelectionError("could not select the hole face")
    return doc.FeatureManager.SimpleHole2(
        units.mm_to_m(diameter_mm),
        True,
        False,
        bool(reverse),
        code,
        0,
        units.mm_to_m(depth_mm or 0.0),
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


def _face_normal_axis(face) -> int | None:
    """The base axis a planar face's normal points along, if any."""
    try:
        normal = binding.value(face.Normal)
        unit = [round(float(value)) for value in normal[:3]]
        for axis in range(3):
            if abs(unit[axis]) == 1:
                return axis
    except Exception:
        pass
    return None


def _find_hole_top_edge(doc, diameter_mm: float, point_mm: list[float], face_axis: int | None = None):
    """Find the circular edge of a drilled hole near the drilled face.

    For through holes there are two matching circles; the one on the face is
    chosen by comparing the coordinate along the face normal.
    """
    expected = math.pi * diameter_mm
    tolerance = max(0.05, expected * 0.002)
    face_coord = point_mm[face_axis] if face_axis is not None else None
    best_index, best_score = None, None
    for item in inspect.list_edges(doc):
        if item.get("curve") != "circle":
            continue
        if abs(item.get("length_mm", 0.0) - expected) > tolerance:
            continue
        center = item.get("center_mm")
        if not center or len(center) < 3:
            continue
        out_of_plane = (
            abs(center[face_axis] - face_coord) if face_axis is not None else 0.0
        )
        in_plane = math.sqrt(
            sum(
                (center[axis] - point_mm[axis]) ** 2
                for axis in range(3)
                if axis != face_axis
            )
        )
        score = (round(out_of_plane, 6), round(in_plane, 6))
        if out_of_plane > 0.05 or in_plane > 0.05:
            continue
        if best_score is None or score < best_score:
            best_index, best_score = item["index"], score
    if best_index is None:
        raise FeatureBuildError(
            "could not find the drilled hole's circular edge",
            hint="the hole edge is used to attach the countersink or thread.",
        )
    return best_index


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
    face, point = _resolve_hole_face(doc, face_index, x_mm, y_mm)
    before = feature_names(doc)
    feature = _simple_hole_feature(
        doc, face, point, diameter_mm, code, depth_mm, reverse
    )
    result = _finish_feature(doc, feature, "simple_hole", name, before=before)
    result["data"]["diameter_mm"] = diameter_mm
    result["data"]["face_index"] = face_index
    result["data"]["position_mm"] = [
        round(units.m_to_mm(value), 4) for value in point
    ]
    result["data"]["hole_semantics"] = "simple_hole_no_holewizard_callout"
    return result


def _hole_depth_valid(end_condition: str, depth_mm: float | None) -> None:
    if end_condition in ("blind", "up_to_next", "mid_plane") and depth_mm is None:
        raise InvalidParameterError(
            f"depth_mm is required for end_condition {end_condition!r}"
        )


def counterbore_hole(
    diameter_mm: float,
    counterbore_diameter_mm: float,
    counterbore_depth_mm: float,
    face_index: int,
    x_mm: float,
    y_mm: float,
    depth_mm: float | None = 10.0,
    end_condition: str = "blind",
    name: str | None = None,
) -> dict:
    """A counterbore is two SimpleHole2 passes from the same face point.

    The counterbore diameter drills to ``counterbore_depth_mm``, the pilot
    diameter continues to the rest of the depth. No sketch is involved, so
    both passes use the same ISelectData point.
    """
    if diameter_mm <= 0 or counterbore_diameter_mm <= diameter_mm:
        raise InvalidParameterError(
            "counterbore_diameter_mm must be larger than diameter_mm"
        )
    if counterbore_depth_mm <= 0:
        raise InvalidParameterError("counterbore_depth_mm must be positive")
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
    _hole_depth_valid(end_condition, depth_mm)
    if end_condition == "blind" and depth_mm is not None:
        if depth_mm <= counterbore_depth_mm:
            raise InvalidParameterError(
                "depth_mm must be deeper than counterbore_depth_mm"
            )
    _, doc, _ = session.active_doc(("part",))
    before = feature_names(doc)
    face, point = _resolve_hole_face(doc, face_index, x_mm, y_mm)
    signature = _planar_face_signature(face)
    fingerprint = _model_fingerprint(doc)
    try:
        pilot = _simple_hole_feature(doc, face, point, diameter_mm, code, depth_mm)
        after_pilot_names = feature_names(doc)
        if pilot is None and not (after_pilot_names - before):
            raise FeatureBuildError(
                "counterbore_hole pilot hole did not build",
                whats_wrong=inspect.whats_wrong(doc),
            )
        pilot_name = _newest_feature_name(doc, before)
        if pilot_name is None:
            raise FeatureBuildError("counterbore_hole pilot feature was not found")
        rebuilt = inspect.rebuild(doc)
        if not rebuilt.get("ok") or rebuilt.get("whats_wrong", {}).get("count", 0):
            raise FeatureBuildError(
                "counterbore_hole pilot did not rebuild cleanly",
                whats_wrong=rebuilt.get("whats_wrong"),
            )
        current_face = _refresh_hole_face(doc, signature, point)
        counterbore = _simple_hole_feature(
            doc, current_face, point, counterbore_diameter_mm, 0, counterbore_depth_mm
        )
        result = _finish_feature(
            doc, counterbore, "counterbore_hole", name, before=before
        )
    except Exception as exc:
        try:
            _rollback_features(doc, before)
            after = _model_fingerprint(doc)
            unchanged = _same_fingerprint(fingerprint, after)
        except Exception as rollback_error:
            raise FeatureBuildError(
                "counterbore creation failed and rollback could not be verified",
                failure=str(exc),
                rollback_failure=str(rollback_error),
                features_after=sorted(feature_names(doc)),
            ) from exc
        if not unchanged:
            raise FeatureBuildError(
                "counterbore creation failed; the model changed after rollback",
                failure=str(exc),
                before_volume_mm3=fingerprint["mass"].get("volume_mm3"),
                after_volume_mm3=after["mass"].get("volume_mm3"),
                features_after=sorted(after["features"]),
            ) from exc
        raise FeatureBuildError(
            "counterbore creation failed; partial cuts were rolled back",
            failure=str(exc),
            rolled_back=True,
            model_unchanged=True,
            volume_mm3=after["mass"].get("volume_mm3"),
            topology=after["topology"],
        ) from exc
    result["data"].update(
        {
            "diameter_mm": diameter_mm,
            "counterbore_diameter_mm": counterbore_diameter_mm,
            "counterbore_depth_mm": counterbore_depth_mm,
            "face_index": face_index,
            "position_mm": [round(units.m_to_mm(value), 4) for value in point],
            "hole_semantics": "compound_cuts_no_holewizard_callout",
        }
    )
    return result


def countersink_hole(
    diameter_mm: float,
    countersink_diameter_mm: float,
    face_index: int,
    x_mm: float,
    y_mm: float,
    angle_deg: float = 90.0,
    depth_mm: float | None = 10.0,
    end_condition: str = "blind",
    name: str | None = None,
) -> dict:
    """Drill a pilot hole and chamfer its top edge into a countersink.

    The chamfer is the measured angle-distance form: ``distance_mm`` is the
    radial width ``(countersink - pilot) / 2`` and the chamfer angle is half
    the countersink's included angle.
    """
    if diameter_mm <= 0 or countersink_diameter_mm <= diameter_mm:
        raise InvalidParameterError(
            "countersink_diameter_mm must be larger than diameter_mm"
        )
    if not 0 < angle_deg < 180:
        raise InvalidParameterError("angle_deg must be between 0 and 180")
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
    _hole_depth_valid(end_condition, depth_mm)
    _, doc, _ = session.active_doc(("part",))
    face, point = _resolve_hole_face(doc, face_index, x_mm, y_mm)
    before = feature_names(doc)
    pilot = _simple_hole_feature(doc, face, point, diameter_mm, code, depth_mm)
    if pilot is None and not (feature_names(doc) - before):
        raise FeatureBuildError(
            "countersink_hole pilot hole did not build",
            whats_wrong=inspect.whats_wrong(doc),
        )
    point_mm = [units.m_to_mm(value) for value in point]
    axis = _face_normal_axis(face)
    edge = _find_hole_top_edge(doc, diameter_mm, point_mm, axis)
    radial_mm = (countersink_diameter_mm - diameter_mm) / 2.0
    session.clear_selection(doc)
    inspect.select_edges(doc, [edge], append=False)
    feature = doc.FeatureManager.InsertFeatureChamfer(
        4,
        CHAMFER_TYPES["angle_distance"],
        units.mm_to_m(radial_mm),
        units.deg_to_rad(angle_deg / 2.0),
        0.0,
        0.0,
        0.0,
        0.0,
    )
    result = _finish_feature(doc, feature, "countersink_hole", name, before=before)
    result["data"].update(
        {
            "diameter_mm": diameter_mm,
            "countersink_diameter_mm": countersink_diameter_mm,
            "angle_deg": angle_deg,
            "face_index": face_index,
            "position_mm": [round(value, 4) for value in point_mm],
            "hole_semantics": "compound_cut_and_chamfer_no_holewizard_callout",
        }
    )
    return result


def tapped_hole(
    diameter_mm: float,
    pitch_mm: float,
    face_index: int,
    x_mm: float,
    y_mm: float,
    depth_mm: float | None = 10.0,
    end_condition: str = "blind",
    drill_diameter_mm: float | None = None,
    note: str | None = None,
    name: str | None = None,
) -> dict:
    """Drill a tap-drill hole and attach a cosmetic thread.

    The drill diameter defaults to the ISO coarse approximation
    ``diameter - pitch``; pass ``drill_diameter_mm`` for an exact table value.
    The thread is cosmetic (no geometry), so the volume equals the drilled
    hole.
    """
    if diameter_mm <= 0 or pitch_mm <= 0:
        raise InvalidParameterError("diameter_mm and pitch_mm must be positive")
    drill = drill_diameter_mm if drill_diameter_mm else diameter_mm - pitch_mm
    if drill <= 0:
        raise InvalidParameterError("the drill diameter must be positive")
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
    _hole_depth_valid(end_condition, depth_mm)
    _, doc, _ = session.active_doc(("part",))
    face, point = _resolve_hole_face(doc, face_index, x_mm, y_mm)
    before = feature_names(doc)
    pilot = _simple_hole_feature(doc, face, point, drill, code, depth_mm)
    if pilot is None and not (feature_names(doc) - before):
        raise FeatureBuildError(
            "tapped_hole drill did not build",
            whats_wrong=inspect.whats_wrong(doc),
        )
    point_mm = [units.m_to_mm(value) for value in point]
    axis = _face_normal_axis(face)
    edge = _find_hole_top_edge(doc, drill, point_mm, axis)
    callout = note or f"M{diameter_mm:g}x{pitch_mm:g}"
    session.clear_selection(doc)
    inspect.select_edges(doc, [edge], append=False)
    # Measured on SW2026 SP0.0: InsertCosmeticThread2's first double lands in
    # the thread Diameter and the second in BlindDepth, despite names.
    feature = doc.FeatureManager.InsertCosmeticThread2(
        2 if end_condition == "through_all" else 0,
        units.mm_to_m(diameter_mm),
        units.mm_to_m(depth_mm or 0.0),
        callout,
    )
    result = _finish_feature(doc, feature, "tapped_hole", name, before=before)
    result["data"].update(
        {
            "diameter_mm": diameter_mm,
            "pitch_mm": pitch_mm,
            "drill_diameter_mm": drill,
            "callout": callout,
            "hole_semantics": "drilled_cut_with_cosmetic_thread_no_holewizard_callout",
            "face_index": face_index,
            "position_mm": [round(value, 4) for value in point_mm],
        }
    )
    return result


def cosmetic_thread(
    edge_index: int,
    depth_mm: float | None = None,
    diameter_mm: float | None = None,
    through: bool = False,
    note: str = "",
    name: str | None = None,
) -> dict:
    """Attach a cosmetic thread to one circular edge.

    The diameter defaults to the edge's own diameter (``length / pi``); pass
    it explicitly for a tapped hole, where the nominal thread diameter is
    larger than the drilled hole. The feature is cosmetic and adds no volume;
    the measured read-back is what proves it.
    """
    if not through and depth_mm is None:
        raise InvalidParameterError(
            "depth_mm is required for a blind thread (or set through=true)"
        )
    _, doc, _ = session.active_doc(("part",))
    edges = [item for item in inspect.list_edges(doc) if item["index"] == edge_index]
    if not edges:
        raise SelectionError(
            f"edge index {edge_index} not found; re-list edges"
        )
    edge_info = edges[0]
    if edge_info.get("curve") != "circle":
        raise InvalidParameterError(
            "a cosmetic thread attaches to a circular edge",
            hint="pick a hole or shaft circle from list_edges.",
        )
    if diameter_mm is None:
        diameter_mm = float(edge_info.get("length_mm", 0.0)) / math.pi
    if diameter_mm <= 0:
        raise InvalidParameterError("could not derive a thread diameter")
    session.clear_selection(doc)
    inspect.select_edges(doc, [edge_index], append=False)
    feature = doc.FeatureManager.InsertCosmeticThread2(
        2 if through else 0,
        units.mm_to_m(diameter_mm),
        units.mm_to_m(depth_mm or 0.0),
        note,
    )
    result = _finish_feature(doc, feature, "cosmetic_thread", name)
    definition = None
    if feature is not None:
        try:
            wrapped = binding.wrap(feature, "IFeature")
            definition = binding.wrap(
                wrapped.GetDefinition(), "ICosmeticThreadFeatureData"
            )
        except Exception:
            definition = None
    data = result["data"]
    data["edge_index"] = edge_index
    data["type"] = "through" if through else "blind"
    data["hole_semantics"] = "drilled_cut_with_cosmetic_thread_no_holewizard_callout"
    if definition is not None:
        for member, key, convert in (
            ("Diameter", "diameter_mm", units.m_to_mm),
            ("BlindDepth", "depth_mm", units.m_to_mm),
        ):
            try:
                data[key] = round(convert(float(binding.value(getattr(definition, member)))), 4)
            except Exception:
                continue
        try:
            data["callout"] = str(binding.value(definition.ThreadCallout) or "")
        except Exception:
            pass
    return result


def dome(
    height_mm: float,
    face_index: int,
    reverse: bool = False,
    elliptic: bool = False,
    name: str | None = None,
) -> dict:
    """Dome a planar face. InsertDome returns void; the tree diff is the judge.

    Measured on SW2026 SP0.0: the face goes in selection mark 1; with mark 0
    the call silently builds nothing. On a circular face the added volume
    matches the spherical-cap formula exactly.
    """
    if height_mm <= 0:
        raise InvalidParameterError("height_mm must be positive")
    _, doc, _ = session.active_doc(("part",))
    session.clear_selection(doc)
    inspect.select_faces(doc, [face_index], append=False, mark=1)
    before = feature_names(doc)
    doc.InsertDome(units.mm_to_m(height_mm), bool(reverse), bool(elliptic))
    result = _finish_feature(doc, None, "dome", name, before=before)
    result["data"].update(
        {"height_mm": height_mm, "face_index": face_index, "reverse": bool(reverse)}
    )
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


# IPartDoc.InsertCombineFeature uses swBodyOperationType_e (not the feature-data
# enum). The only insertion operation used here is the measured subtraction
# seed; Add/Common are applied through ICombineBodiesFeatureData.OperationType.
_COMBINE_INSERT_SUBTRACT = 15902
_COMBINE_FEATURE_OPERATION = {"add": 0, "subtract": 1, "common": 2}


def _combine_dispatch_array(body):
    import pythoncom
    import win32com.client

    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [body]
    )


def _combine_failure(
    doc, operation: str, original_names: set[str], before: dict, failure: Exception
):
    """Remove only features created by this call, then prove the model restored."""
    rollback_error = None
    try:
        if feature_names(doc) != original_names:
            _rollback_features(doc, original_names)
    except Exception as exc:
        rollback_error = f"{type(exc).__name__}: {exc}"
    try:
        after = _model_fingerprint(doc)
        unchanged = _same_fingerprint(before, after)
    except Exception as exc:
        after = None
        unchanged = False
        rollback_error = rollback_error or f"fingerprint failed: {type(exc).__name__}: {exc}"
    if unchanged:
        raise FeatureBuildError(
            f"combine_bodies {operation} failed; the model was restored",
            operation=operation,
            failure=f"{type(failure).__name__}: {failure}",
            rolled_back=True,
            model_unchanged=True,
            rollback_error=rollback_error,
        ) from failure
    raise FeatureBuildError(
        f"combine_bodies {operation} failed and rollback could not be verified",
        operation=operation,
        failure=f"{type(failure).__name__}: {failure}",
        rolled_back=False,
        model_unchanged=False,
        rollback_error=rollback_error,
        before=before,
        after=after,
        hint="Inspect the active model and restore its checkpoint if needed.",
    ) from failure


def combine_bodies(
    operation: str, main_body_index: int, tool_body_index: int
) -> dict:
    """Combine one indexed tool body into one indexed main body.

    Subtraction is directly measured through IPartDoc.InsertCombineFeature.
    Add/common create that known-good subtraction feature, then change only the
    feature-data OperationType through IFeature.ModifyDefinition. Geometry
    support is bounded by the exact live fixtures documented in COM-QUIRKS.md.
    """
    if operation not in _COMBINE_FEATURE_OPERATION:
        raise InvalidParameterError(
            f"unknown combine operation {operation!r}",
            available=sorted(_COMBINE_FEATURE_OPERATION),
        )
    for name, index in (
        ("main_body_index", main_body_index),
        ("tool_body_index", tool_body_index),
    ):
        if type(index) is not int or index < 0:
            raise InvalidParameterError(f"{name} must be a non-negative integer")
    if main_body_index == tool_body_index:
        raise InvalidParameterError("main_body_index and tool_body_index must differ")

    _, doc, _ = session.active_doc(("part",))
    bodies = inspect._bodies(doc)
    for name, index in (
        ("main_body_index", main_body_index),
        ("tool_body_index", tool_body_index),
    ):
        if index >= len(bodies):
            raise SelectionError(
                f"{name} {index} is out of range for {len(bodies)} current bodies"
            )
        body_type = int(binding.value(bodies[index].GetType()))
        if body_type != inspect.BODY_TYPES["solid"]:
            raise InvalidParameterError(f"{name} must refer to a solid body")

    original_names = feature_names(doc)
    before = _model_fingerprint(doc)
    try:
        session.clear_selection(doc)
        # Use the exact enumeration that resolved both public indices; a second
        # GetBodies2 call could reorder bodies between validation and selection.
        select_data = inspect.create_select_data(doc)
        if select_data is None:
            raise ComCallError("could not create selection data for body combination")
        selected = 0
        for body in (bodies[main_body_index], bodies[tool_body_index]):
            wrapped_body = binding.wrap(body, "IBody2")
            if not wrapped_body.Select2(bool(selected), select_data):
                raise SelectionError(f"could not select combine body {selected}")
            selected += 1
        if selected != 2:
            raise SelectionError(f"expected to select 2 bodies, selected {selected}")

        main_body = binding.wrap(bodies[main_body_index], "IBody2")
        tool_body = binding.wrap(bodies[tool_body_index], "IBody2")
        part = binding.wrap(doc, "IPartDoc")
        insert_result = part.InsertCombineFeature(
            _COMBINE_INSERT_SUBTRACT,
            main_body,
            _combine_dispatch_array(tool_body),
        )

        after_insert_names = feature_names(doc)
        created_names = after_insert_names - original_names
        if len(created_names) != 1:
            raise FeatureBuildError(
                "subtraction seed did not create exactly one new feature",
                insert_result=bool(insert_result),
                new_features=sorted(created_names),
            )
        feature = next(
            (
                binding.wrap(candidate, "IFeature")
                for candidate in session.iter_features(doc)
                if str(binding.value(candidate.Name)) in created_names
            ),
            None,
        )
        if feature is None or str(feature.GetTypeName2()) != "CombineBodies":
            raise FeatureBuildError(
                "subtraction seed did not produce a CombineBodies feature",
                new_features=sorted(created_names),
            )

        modify_result = None
        if operation != "subtract":
            raw_definition = feature.GetDefinition()
            if raw_definition is None:
                raise ComCallError("CombineBodies.GetDefinition returned None")
            definition = binding.wrap(
                raw_definition, "ICombineBodiesFeatureData"
            )
            definition.OperationType = _COMBINE_FEATURE_OPERATION[operation]
            modify_result = bool(feature.ModifyDefinition(definition, doc, None))
            if not modify_result:
                raise FeatureBuildError(
                    "SOLIDWORKS refused the CombineBodies feature-data update",
                    operation=operation,
                )

        rebuild = inspect.rebuild(doc)
        mass_properties = inspect.mass_properties(doc)
        body_count = len(inspect._bodies(doc, "solid"))
        if not rebuild.get("ok") or rebuild.get("whats_wrong", {}).get("count", 0):
            raise FeatureBuildError(
                "combine_bodies built a feature but the model reports errors",
                operation=operation,
                rebuild=rebuild,
            )
        if body_count != 1:
            raise FeatureBuildError(
                "combine_bodies did not produce exactly one solid body",
                operation=operation,
                body_count=body_count,
            )
        if mass_properties.get("volume_mm3") is None:
            raise FeatureBuildError(
                "combine_bodies produced no measurable volume",
                operation=operation,
                mass_properties=mass_properties,
            )
        return {
            "data": {
                "operation": operation,
                "main_body_index": main_body_index,
                "tool_body_index": tool_body_index,
                "feature": next(iter(created_names)),
            },
            "evidence": {
                "insert_result": bool(insert_result),
                "modify_definition_result": modify_result,
                "feature_tree_before": sorted(original_names),
                "feature_tree_after": sorted(feature_names(doc)),
                "rebuild": rebuild,
                "whats_wrong": rebuild.get("whats_wrong", {}),
                "body_count": body_count,
                "mass_properties": mass_properties,
            },
        }
    except Exception as exc:
        _combine_failure(doc, operation, original_names, before, exc)
