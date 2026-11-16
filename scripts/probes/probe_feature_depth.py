#!/usr/bin/env python
"""Live probe: Wave-1 feature-depth actuators on SW2026 SP0.0.

Questions this script answers before the tools are written:

1. ``InsertFeatureChamfer``'s ``ChamferType``: which value means which
   chamfer, and what does the current ``CHAMFER_EQUAL_DISTANCE = 1`` actually
   build? (The typelib enum says EqualDistance=16, AngleDistance=1.)
2. Extrude end conditions: which selection (sketch and/or target, which mark)
   makes up-to-surface/up-to-vertex build, and what do ``TranslateSurface1``
   and ``OffsetReverse1`` do for offset-from-surface? How is a body selected
   for up-to-body?
3. ``FeatureRevolveCut2`` argument semantics on this build.
4. ``FeatureCutThin2`` / ``IModelDoc2.FeatureBossThin2``: which ``RevThinDir``
   value puts the wall on which side, and does a through-all thin cut build?
5. ``FeatureFillet3``: face fillet selection marks, variable-radius array
   marshalling, asymmetric fillet.
6. ``InsertCosmeticThread2`` parameters and read-back.
7. ``InsertDome`` (void return): geometry and volume against the spherical-cap
   formula.
8. ``InsertRib2`` retry (known to build nothing on this build).

The Hole Wizard spike is opt-in (``--hole-wizard``): the previous attempt
crashed SOLIDWORKS in ``mfc140u.dll`` - save your work first.

Creates scratch parts and discards all of them (never saves over anything).
Run with SOLIDWORKS open.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solidworks_mcp.com import binding, units  # noqa: E402
from solidworks_mcp.domain import (  # noqa: E402
    documents,
    features,
    inspect,
    session,
    sketch,
)

RESULTS: list[dict] = []
CREATED: list[str] = []


def probe(name, fn):
    try:
        RESULTS.append({"probe": name, "ok": True, "result": fn()})
    except Exception as exc:  # noqa: BLE001 - every failure is a probe result
        RESULTS.append(
            {
                "probe": name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4),
            }
        )
    return RESULTS[-1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def new_part(label: str):
    documents.new_document("part")
    _, doc, _ = session.active_doc(("part",))
    title = str(binding.value(doc.GetTitle))
    CREATED.append(title)
    return doc


def volume_mm3(doc) -> float | None:
    try:
        return inspect.mass_properties(doc).get("volume_mm3")
    except Exception:
        return None


def bbox_mm(doc) -> dict | None:
    try:
        return inspect.bounding_box(doc)
    except Exception:
        return None


def attempt(doc, label: str, call) -> dict:
    """Run one raw COM call; judge it by tree diff + rebuild + volume."""
    before = features.feature_names(doc)
    info: dict = {"label": label}
    try:
        returned = call()
        info["returned_none"] = returned is None
    except Exception as exc:  # noqa: BLE001
        info["call_error"] = f"{type(exc).__name__}: {exc}"
    added = sorted(features.feature_names(doc) - before)
    info["added"] = added
    try:
        rebuild = inspect.rebuild(doc)
        info["rebuild_ok"] = rebuild.get("ok")
        info["whats_wrong"] = rebuild.get("whats_wrong")
    except Exception as exc:  # noqa: BLE001
        info["rebuild_error"] = f"{type(exc).__name__}: {exc}"
    info["volume_mm3"] = volume_mm3(doc)
    return info


def box(doc, x0=-20.0, y0=-20.0, x1=20.0, y1=20.0, height_mm=40.0):
    sketch.create_sketch("Front Plane")
    sketch.rectangle(x0, y0, x1, y1)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=height_mm)


def box_volume(x0, y0, x1, y1, height_mm) -> float:
    return (x1 - x0) * (y1 - y0) * height_mm


def find_top_line_edge(doc, height_mm: float) -> int | None:
    for edge in inspect.list_edges(doc):
        if edge.get("curve") != "line" or edge.get("length_mm", 0) < 5:
            continue
        start = edge.get("start_mm") or []
        end = edge.get("end_mm") or []
        if len(start) >= 3 and len(end) >= 3:
            if abs(start[2] - height_mm) < 0.01 and abs(end[2] - height_mm) < 0.01:
                return edge["index"]
    return None


def find_face(doc, normal: str, surface: str = "plane") -> int | None:
    for face in inspect.list_faces(doc, surface_type=surface, normal=normal):
        return face["index"]
    return None


# ---------------------------------------------------------------------------
# 1. chamfer type mapping
# ---------------------------------------------------------------------------


def probe_chamfer_types():
    results = []
    edge_case = 40.0
    cases = [
        ("type1_w10_a45", 4, 1, 10.0, 45.0, 0.0),
        ("type1_w10_a30", 4, 1, 10.0, 30.0, 0.0),
        ("type16_w10_a30", 4, 16, 10.0, 30.0, 0.0),
        ("type2_w10_other4", 4, 2, 10.0, 45.0, 4.0),
        ("type1_w10_a45_opt1", 1, 1, 10.0, 45.0, 0.0),
    ]
    for label, options, ctype, width, angle, other in cases:
        doc = new_part(label)
        box(doc)
        edge = find_top_line_edge(doc, 40.0)
        info = {"case": label, "edge": edge, "before_volume_mm3": volume_mm3(doc)}
        if edge is None:
            results.append({**info, "error": "no top edge found"})
            continue
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc, edge=edge: (
                    session.clear_selection(doc),
                    inspect.select_edges(doc, [edge], append=False),
                    doc.FeatureManager.InsertFeatureChamfer(
                        options,
                        ctype,
                        units.mm_to_m(width),
                        units.deg_to_rad(angle),
                        units.mm_to_m(other),
                        0.0,
                        0.0,
                        0.0,
                    ),
                ),
            )
        )
        if info.get("before_volume_mm3") is not None and info.get("volume_mm3"):
            info["removed_mm3"] = round(
                info["before_volume_mm3"] - info["volume_mm3"], 4
            )
        info["expected_equal_distance_mm3"] = round(
            0.5 * width * width * edge_case, 3
        )
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# 2. extrude end conditions
# ---------------------------------------------------------------------------


def _extrude_args(t1, d1, merge=True, translate_surface=False, offset_reverse=False,
                  t2=0, d2=0.0):
    return (
        True,  # Sd
        False,  # Flip
        False,  # Dir (same convention as domain.features: False extrudes +Z)
        t1,
        t2,
        units.mm_to_m(d1),
        units.mm_to_m(d2),
        False,  # Dchk1
        False,  # Dchk2
        False,  # Ddir1
        False,  # Ddir2
        0.0,  # Dang1
        0.0,  # Dang2
        bool(offset_reverse),  # OffsetReverse1
        False,  # OffsetReverse2
        bool(translate_surface),  # TranslateSurface1
        False,  # TranslateSurface2
        bool(merge),  # Merge
        True,  # UseFeatScope
        True,  # UseAutoSelect
        0,  # T0
        0.0,  # StartOffset
        False,  # FlipStartOffset
    )


def _setup_plane_and_sketch(label, plane_offset_mm=30.0):
    """Fresh part: offset plane at z=plane_offset, circle sketch on Front."""
    doc = new_part(label)
    features.create_reference_plane(
        kind="offset", plane="Front Plane", distance_mm=plane_offset_mm,
        name="PROBE PLANE",
    )
    sketch.create_sketch("Front Plane")
    sketch.circle(0.0, 0.0, 5.0)
    sketch.exit_sketch()
    return doc


def probe_up_to_surface():
    """Try the selection schemes for T1=4; expect a 30 mm cylinder."""
    results = []
    trials = [
        ("no_reference_selected", None, None),
        ("target_mark0", None, 0),
        ("sketch0_target1", 0, 1),
        ("target0_sketch1", 1, 0),
    ]
    for label, sketch_mark, target_mark in trials:
        doc = _setup_plane_and_sketch("upto_" + label)
        info = {"case": label}
        if target_mark is not None:
            session.select_plane(doc, "PROBE PLANE", mark=target_mark, append=False)
        if sketch_mark is not None:
            session.select_sketch(doc, "Sketch1", append=True, mark=sketch_mark)
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc: doc.FeatureManager.FeatureExtrusion3(
                    *_extrude_args(4, 0.0)
                ),
            )
        )
        info["bbox_mm"] = bbox_mm(doc)
        results.append(info)
    return results


def probe_offset_from_surface():
    """T1=5, offset 5 mm: does TranslateSurface/OffsetReverse move the end?"""
    results = []
    for label, translate, reverse in [
        ("translate_false", False, False),
        ("translate_true", True, False),
        ("translate_true_reverse", True, True),
    ]:
        doc = _setup_plane_and_sketch("offset_" + label)
        session.select_plane(doc, "PROBE PLANE", mark=0, append=False)
        info = {"case": label}
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc, t=translate, r=reverse: (
                    doc.FeatureManager.FeatureExtrusion3(
                        *_extrude_args(5, 5.0, translate_surface=t, offset_reverse=r)
                    )
                ),
            )
        )
        info["bbox_mm"] = bbox_mm(doc)
        results.append(info)
    return results


def probe_up_to_vertex():
    """T1=3 with a vertex selected; expect a cylinder to the vertex's height."""
    doc = new_part("upto_vertex")
    features.create_reference_plane(
        kind="offset", plane="Front Plane", distance_mm=40.0, name="PROBE TALL"
    )
    # Tall thin body (separate body: merge off) reaches z=40.
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-30.0, -30.0, -20.0, -20.0)
    sketch.exit_sketch()
    doc.FeatureManager.FeatureExtrusion3(*_extrude_args(0, 40.0, merge=False))
    inspect.rebuild(doc)
    # Target sketch.
    sketch.create_sketch("Front Plane")
    sketch.circle(10.0, 10.0, 3.0)
    sketch.exit_sketch()
    vertex = None
    for item in inspect.list_vertices(doc):
        point = item.get("point_mm") or []
        if len(point) >= 3 and abs(point[2] - 40.0) < 0.01:
            vertex = item["index"]
            break
    info = {"vertex": vertex}
    if vertex is not None:
        session.select_sketch(doc, "Sketch2", append=False, mark=0)
        inspect.select_vertices(doc, [vertex], append=True, mark=1)
    info.update(
        attempt(
            doc,
            "upto_vertex",
            lambda doc=doc: doc.FeatureManager.FeatureExtrusion3(
                *_extrude_args(3, 0.0)
            ),
        )
    )
    info["bbox_mm"] = bbox_mm(doc)
    return info


def probe_up_to_body():
    """T1=7 with a second body selected; expected stop at the body's bottom."""
    doc = new_part("upto_body")
    # Main body: plate z 0..10.
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-30.0, -30.0, 30.0, 30.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=10.0)
    # Second body: block z 30..50, unmerged.
    features.create_reference_plane(
        kind="offset", plane="Front Plane", distance_mm=30.0, name="PROBE B2"
    )
    sketch.create_sketch("PROBE B2")
    sketch.rectangle(-15.0, -15.0, 15.0, 15.0)
    sketch.exit_sketch()
    doc.FeatureManager.FeatureExtrusion3(*_extrude_args(0, 20.0, merge=False))
    inspect.rebuild(doc)
    # Target: circle on the plate's top plane extruded up-to-body.
    sketch.create_sketch("Front Plane")
    sketch.circle(0.0, 0.0, 5.0)
    sketch.exit_sketch()
    bodies = inspect.list_bodies(doc)
    info: dict = {"bodies": bodies}
    if len(bodies) >= 2:
        target = inspect._bodies(doc)[1]
        session.clear_selection(doc)
        data = inspect.create_select_data(doc, 1)
        selected = inspect.select_entity(target, append=False, mark=1, data=data)
        info["body_selected"] = selected
        info["sketch_selected"] = session.select_sketch(
            doc, "Sketch3", append=True, mark=0
        )
        info.update(
            attempt(
                doc,
                "upto_body",
                lambda doc=doc: doc.FeatureManager.FeatureExtrusion3(
                    *_extrude_args(7, 0.0)
                ),
            )
        )
    info["bbox_mm"] = bbox_mm(doc)
    return info


# ---------------------------------------------------------------------------
# 3. revolve cut
# ---------------------------------------------------------------------------


def probe_revolve_cut():
    """Cut a full 360-degree ring out of a 40 mm cube."""
    doc = new_part("revolve_cut")
    box(doc)
    before = volume_mm3(doc)
    sketch.create_sketch("Right Plane")
    sketch.rectangle(5.0, -30.0, 15.0, 30.0)
    sketch.line(0.0, -35.0, 0.0, 35.0, construction=True)
    sketch.exit_sketch()
    session.clear_selection(doc)
    used = features._select_sketch_centerline(doc)
    info = {"axis_selected": used, "before_volume_mm3": before}
    info.update(
        attempt(
            doc,
            "revolve_cut",
            lambda doc=doc: doc.FeatureManager.FeatureRevolveCut2(
                units.deg_to_rad(360.0),
                False,
                0.0,
                0,
                0,
                False,
                False,
                False,
                False,
                False,
            ),
        )
    )
    if before is not None and info.get("volume_mm3") is not None:
        info["removed_mm3"] = round(before - info["volume_mm3"], 4)
    info["expected_ring_removed_mm3"] = round(math.pi * (225.0 - 25.0) * 40.0, 4)
    return info


# ---------------------------------------------------------------------------
# 4. thin features
# ---------------------------------------------------------------------------


def _thin_args(t1, d1, thickness_mm, rev_dir, cap_ends=0, dir_flag=True):
    return (
        True,  # Sd
        False,  # Flip
        bool(dir_flag),  # Dir
        t1,
        0,  # T2
        units.mm_to_m(d1),
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
        int(rev_dir),  # RevThinDir
        int(cap_ends),  # CapEnds
        False,  # AddBends
        0.0,  # BendRad
        True,  # UseFeatScope
        True,  # UseAutoSelect
        0,  # T0
        0.0,  # StartOffset
        False,  # FlipStartOffset
    )


def probe_thin_cut():
    """Through-all thin cut of a circle r=20 on a 100x100x10 plate."""
    results = []
    for rev_dir in (0, 1, 2):
        doc = new_part(f"thin_cut_{rev_dir}")
        sketch.create_sketch("Front Plane")
        sketch.rectangle(-50.0, -50.0, 50.0, 50.0)
        sketch.exit_sketch()
        features.boss_extrude(depth_mm=10.0)
        before = volume_mm3(doc)
        sketch.create_sketch("Front Plane")
        sketch.circle(0.0, 0.0, 20.0)
        sketch.exit_sketch()
        info = {"case": f"rev_dir={rev_dir}", "before_volume_mm3": before}
        info.update(
            attempt(
                doc,
                f"thin_cut_{rev_dir}",
                lambda doc=doc, r=rev_dir: (
                    doc.FeatureManager.FeatureCutThin2(*_thin_args(1, 0.0, 2.0, r))
                ),
            )
        )
        if before is not None and info.get("volume_mm3") is not None:
            info["removed_mm3"] = round(before - info["volume_mm3"], 4)
        # mean-radius ring: 2*pi*20*2*10
        info["expected_ring_mm3"] = round(2 * math.pi * 20.0 * 2.0 * 10.0, 3)
        results.append(info)
    return results


def probe_thin_boss():
    """Thin boss on FeatureManager.FeatureCutThin2's boss counterpart."""
    doc = new_part("thin_boss")
    before = volume_mm3(doc)
    sketch.create_sketch("Front Plane")
    sketch.circle(0.0, 0.0, 20.0)
    sketch.exit_sketch()
    info = {"before_volume_mm3": before}
    info.update(
        attempt(
            doc,
            "thin_boss",
            lambda doc=doc: doc.FeatureBossThin2(
                *_thin_args(0, 10.0, 2.0, 0)[:24]
            ),
        )
    )
    if before is not None and info.get("volume_mm3") is not None:
        info["added_mm3"] = round(info["volume_mm3"] - before, 4)
    info["expected_ring_mm3"] = round(2 * math.pi * 20.0 * 2.0 * 10.0, 3)
    return info


# ---------------------------------------------------------------------------
# 5. fillet kinds
# ---------------------------------------------------------------------------


def probe_fillet_face_marks():
    results = []
    for label, top_mark, front_mark in [
        ("top1_front2", 1, 2),
        ("top0_front0", 0, 0),
        ("top0_front1", 0, 1),
    ]:
        doc = new_part("fillet_face_" + label)
        box(doc)
        before = volume_mm3(doc)
        top = find_face(doc, "+z")
        front = find_face(doc, "+y")
        info = {"case": label, "top": top, "front": front, "before_volume_mm3": before}
        if top is None or front is None:
            info["error"] = "faces not found"
            results.append(info)
            continue
        session.clear_selection(doc)
        inspect.select_faces(doc, [top], append=False, mark=top_mark)
        inspect.select_faces(doc, [front], append=True, mark=front_mark)
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc: doc.FeatureManager.FeatureFillet3(
                    3,
                    units.mm_to_m(6.0),
                    0.0,
                    0.0,
                    2,  # swFeatureFilletType_Face
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        )
        if before is not None and info.get("volume_mm3") is not None:
            info["removed_mm3"] = round(before - info["volume_mm3"], 4)
        info["expected_removed_mm3"] = round((1 - math.pi / 4) * 36.0 * 40.0, 3)
        results.append(info)
    return results


def probe_fillet_variable_radius():
    results = []
    for label, options, radii in [
        ("varradius_list", 7, [3.0, 8.0]),
        ("varradius_tuple", 7, (3.0, 8.0)),
        ("varradius_none", 7, None),
    ]:
        doc = new_part("fillet_var_" + label)
        box(doc)
        before = volume_mm3(doc)
        edge = find_top_line_edge(doc, 40.0)
        info = {"case": label, "edge": edge, "before_volume_mm3": before}
        if edge is None:
            results.append({**info, "error": "no edge"})
            continue
        session.clear_selection(doc)
        inspect.select_edges(doc, [edge], append=False)
        payload = (
            [units.mm_to_m(value) for value in radii] if radii is not None else None
        )
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc, o=options, r=payload: doc.FeatureManager.FeatureFillet3(
                    o,
                    units.mm_to_m(5.0),
                    0.0,
                    0.0,
                    1,  # swFeatureFilletType_VariableRadius
                    0,
                    0,
                    r,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        )
        if before is not None and info.get("volume_mm3") is not None:
            info["removed_mm3"] = round(before - info["volume_mm3"], 4)
        results.append(info)
    return results


def probe_fillet_asymmetric():
    doc = new_part("fillet_asym")
    box(doc)
    before = volume_mm3(doc)
    edge = find_top_line_edge(doc, 40.0)
    info = {"edge": edge, "before_volume_mm3": before}
    if edge is not None:
        session.clear_selection(doc)
        inspect.select_edges(doc, [edge], append=False)
        info.update(
            attempt(
                doc,
                "asymmetric",
                lambda doc=doc: doc.FeatureManager.FeatureFillet3(
                    3 | 16384,
                    units.mm_to_m(6.0),
                    0.0,
                    0.0,
                    0,
                    0,
                    0,
                    None,
                    [units.mm_to_m(4.0)],
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        )
        if before is not None and info.get("volume_mm3") is not None:
            info["removed_mm3"] = round(before - info["volume_mm3"], 4)
    return info


# ---------------------------------------------------------------------------
# 6. cosmetic thread
# ---------------------------------------------------------------------------


def probe_cosmetic_thread():
    doc = new_part("cosmetic_thread")
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-10.0, -10.0, 10.0, 10.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=20.0)
    top = find_face(doc, "+z")
    features.simple_hole(6.0, top, 10.0, 10.0, end_condition="through_all")
    circle = None
    for edge in inspect.list_edges(doc):
        if edge.get("curve") == "circle" and abs(edge.get("length_mm", 0) - math.pi * 6) < 0.1:
            circle = edge["index"]
            break
    info: dict = {"circle_edge": circle}
    if circle is None:
        info["error"] = "hole circle not found"
        return info
    session.clear_selection(doc)
    inspect.select_edges(doc, [circle], append=False)
    info.update(
        attempt(
            doc,
            "thread_through",
            lambda doc=doc: doc.FeatureManager.InsertCosmeticThread2(
                2, 0.0, 0.0, "M6x1"
            ),
        )
    )
    if not info.get("added"):
        session.clear_selection(doc)
        inspect.select_edges(doc, [circle], append=False)
        info.update(
            attempt(
                doc,
                "thread_blind",
                lambda doc=doc: doc.FeatureManager.InsertCosmeticThread2(
                    0, units.mm_to_m(15.0), units.mm_to_m(15.0), "M6x1"
                ),
            )
        )
    # Read the thread data back if a feature appeared.
    for name in info.get("added") or []:
        try:
            for feature in session.iter_features(doc):
                if str(binding.value(feature.Name)) != name:
                    continue
                definition = binding.wrap(feature.GetDefinition(), "ICosmeticThreadFeatureData")
                info["thread_data"] = {
                    "diameter_mm": round(units.m_to_mm(float(binding.value(definition.Diameter))), 4),
                    "depth_mm": round(units.m_to_mm(float(binding.value(definition.Depth))), 4),
                    "note": str(binding.value(definition.ThreadCallout) or ""),
                }
                break
        except Exception as exc:  # noqa: BLE001
            info["thread_data_error"] = f"{type(exc).__name__}: {exc}"
    return info


# ---------------------------------------------------------------------------
# 7. dome
# ---------------------------------------------------------------------------


def probe_dome():
    doc = new_part("dome")
    sketch.create_sketch("Front Plane")
    sketch.circle(0.0, 0.0, 20.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=30.0)
    top = find_face(doc, "+z", surface="plane")
    before = volume_mm3(doc)
    info: dict = {"top_face": top, "before_volume_mm3": before}
    if top is None:
        info["error"] = "no top face"
        return info
    session.clear_selection(doc)
    inspect.select_faces(doc, [top], append=False)
    info.update(
        attempt(
            doc,
            "dome",
            lambda doc=doc: doc.InsertDome(units.mm_to_m(10.0), False, False),
        )
    )
    info["bbox_mm"] = bbox_mm(doc)
    if before is not None and info.get("volume_mm3") is not None:
        info["added_mm3"] = round(info["volume_mm3"] - before, 4)
    radius, height = 20.0, 10.0
    info["expected_cap_mm3"] = round(
        math.pi * height / 6.0 * (3 * radius * radius + height * height), 4
    )
    return info


# ---------------------------------------------------------------------------
# 8. rib retry
# ---------------------------------------------------------------------------


def probe_rib():
    doc = new_part("rib")
    # Plate 60x40x10 plus a wall 60x10x30 standing on it.
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-30.0, -20.0, 30.0, 20.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=10.0)
    sketch.create_sketch("Top Plane")
    sketch.rectangle(-30.0, -20.0, 30.0, -10.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=30.0)
    sketch.create_sketch("Right Plane")
    sketch.line(-10.0, 0.0, 0.0, 10.0, construction=False)
    sketch.exit_sketch()
    info = attempt(
        doc,
        "rib",
        lambda doc=doc: doc.InsertRib2(
            False,
            False,
            units.mm_to_m(5.0),
            0,
            False,
            False,
            False,
            0.0,
            True,
        ),
    )
    info["bbox_mm"] = bbox_mm(doc)
    return info


# ---------------------------------------------------------------------------
# 9. optional: Hole Wizard spike (crash risk; opt-in only)
# ---------------------------------------------------------------------------


def probe_hole_wizard():
    """One call only. The 2026-09-26 attempt crashed in mfc140u.dll."""
    doc = new_part("hole_wizard")
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-20.0, -20.0, 20.0, 20.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=10.0)
    top = find_face(doc, "+z")
    info: dict = {"top_face": top}
    if top is None:
        info["error"] = "no top face"
        return info
    session.clear_selection(doc)
    inspect.select_faces(doc, [top], append=False)
    # ISO, plain hole, blind; the parameter set is the safest documented one.
    info.update(
        attempt(
            doc,
            "hole_wizard5",
            lambda doc=doc: doc.FeatureManager.HoleWizard5(
                0,   # GenericHoleType: counterbore? (0 = hole)
                0,   # StandardIndex (ISO=?)
                0,   # FastenerTypeIndex
                "M6",  # SSize
                0,   # EndType: blind
                units.mm_to_m(6.0),   # Diameter
                units.mm_to_m(10.0),  # Depth
                0.0,  # Length
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                "1",  # ThreadClass
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ),
        )
    )
    return info


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hole-wizard",
        action="store_true",
        help="also run the single Hole Wizard call (crash risk; save work first)",
    )
    args = parser.parse_args()

    application = session.app()

    probe("chamfer_types", probe_chamfer_types)
    probe("up_to_surface", probe_up_to_surface)
    probe("offset_from_surface", probe_offset_from_surface)
    probe("up_to_vertex", probe_up_to_vertex)
    probe("up_to_body", probe_up_to_body)
    probe("revolve_cut", probe_revolve_cut)
    probe("thin_cut", probe_thin_cut)
    probe("thin_boss", probe_thin_boss)
    probe("fillet_face_marks", probe_fillet_face_marks)
    probe("fillet_variable_radius", probe_fillet_variable_radius)
    probe("fillet_asymmetric", probe_fillet_asymmetric)
    probe("cosmetic_thread", probe_cosmetic_thread)
    probe("dome", probe_dome)
    probe("rib", probe_rib)
    if args.hole_wizard:
        probe("hole_wizard", probe_hole_wizard)

    for title in CREATED:
        try:
            for raw in application.GetDocuments() or []:
                doc = session.wrap_doc(raw)
                if str(binding.value(doc.GetTitle)) == title:
                    doc.SetSaveFlag()
                    application.CloseDoc(title)
        except Exception as exc:  # noqa: BLE001
            RESULTS.append(
                {
                    "probe": f"close:{title}",
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    print(json.dumps({"probes": RESULTS}, indent=2, default=str))
    failed = [item for item in RESULTS if not item["ok"]]
    print(f"\nPROBE: {len(RESULTS) - len(failed)}/{len(RESULTS)} completed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
