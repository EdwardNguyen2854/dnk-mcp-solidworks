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


def cut_extrude(
    depth_mm: float | None = None,
    end_condition: str = "blind",
    draft_deg: float = 0.0,
    reverse: bool = False,
    both_directions: bool = False,
    normal_cut: bool = False,
    name: str | None = None,
) -> dict:
    _, doc, _ = session.active_doc(("part",))
    single, flip, direction, t1, t2, d1, d2, dr1, dr2, di1, di2, an1, an2 = (
        _extrusion_arguments(depth_mm, end_condition, draft_deg, reverse, both_directions)
    )[:13]
    arguments = [
        single,
        flip,
        direction,
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
    feature = doc.FeatureManager.FeatureCut4(*arguments)
    return _finish_feature(doc, feature, "cut_extrude", name)


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
