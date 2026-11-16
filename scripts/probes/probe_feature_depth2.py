#!/usr/bin/env python
"""Live probe #2: follow-ups from probe_feature_depth.py.

1. offset-from-surface with the working selection scheme
   (sketch mark 0 + target mark 1) and both TranslateSurface values.
2. up-to-body with the body selected directly through ``IBody2.Select2``
   (``inspect.select_entity`` cannot select bodies: no Select4, and its
   Select2 fallback passes an int where an ISelectData is required).
3. Chamfer type 16 ("equal distance" in the typelib): which parameter
   carries the distance?
4. Variable-radius fillet read-back through IVariableFilletFeatureData2.
5. Cosmetic thread: where does the feature live in the tree (top-level or
   nested), and can ICosmeticThreadFeatureData read it back?
6. Dome: which face/selection makes IModelDoc2.InsertDome build.

Scratch parts only; discarded, never saved. Run with SOLIDWORKS open.
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
APPLICATION = None


def close_created_since(index: int) -> None:
    """Discard scratch documents created by one probe (RAM hygiene)."""
    if APPLICATION is None:
        return
    for title in CREATED[index:]:
        try:
            for raw in APPLICATION.GetDocuments() or []:
                doc = session.wrap_doc(raw)
                if str(binding.value(doc.GetTitle)) == title:
                    doc.SetSaveFlag()
                    APPLICATION.CloseDoc(title)
        except Exception as exc:  # noqa: BLE001
            print(f"  cleanup failed for {title}: {type(exc).__name__}: {exc}")


def probe(name, fn):
    created_before = len(CREATED)
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
    close_created_since(created_before)
    print(f"[probe] {name}: {json.dumps(RESULTS[-1], default=str)[:400]}", flush=True)
    return RESULTS[-1]


def new_part(label: str):
    documents.new_document("part")
    _, doc, _ = session.active_doc(("part",))
    CREATED.append(str(binding.value(doc.GetTitle)))
    return doc


def volume_mm3(doc):
    try:
        return inspect.mass_properties(doc).get("volume_mm3")
    except Exception:
        return None


def bbox_mm(doc):
    try:
        return inspect.bounding_box(doc)
    except Exception:
        return None


def attempt(doc, label: str, call) -> dict:
    before = features.feature_names(doc)
    info: dict = {"label": label}
    try:
        returned = call()
        info["returned_none"] = returned is None
        if returned is not None:
            try:
                wrapped = binding.wrap(returned, "IFeature")
                info["returned_name"] = str(binding.value(wrapped.Name))
                info["returned_type"] = str(wrapped.GetTypeName2())
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        info["call_error"] = f"{type(exc).__name__}: {exc}"
    info["added"] = sorted(features.feature_names(doc) - before)
    try:
        rebuild = inspect.rebuild(doc)
        info["rebuild_ok"] = rebuild.get("ok")
        info["whats_wrong"] = rebuild.get("whats_wrong")
    except Exception as exc:  # noqa: BLE001
        info["rebuild_error"] = f"{type(exc).__name__}: {exc}"
    info["volume_mm3"] = volume_mm3(doc)
    info["bbox_mm"] = bbox_mm(doc)
    return info


def find_face(doc, normal: str, surface: str = "plane"):
    for face in inspect.list_faces(doc, surface_type=surface, normal=normal):
        return face["index"]
    return None


def _extrude_args(t1, d1, translate_surface=False, offset_reverse=False, merge=True):
    return (
        True, False, False, t1, 0,
        units.mm_to_m(d1), 0.0,
        False, False, False, False, 0.0, 0.0,
        bool(offset_reverse), False,
        bool(translate_surface), False,
        bool(merge), True, True, 0, 0.0, False,
    )


def _plane_sketch(label, offset_mm=30.0):
    doc = new_part(label)
    features.create_reference_plane(
        kind="offset", plane="Front Plane", distance_mm=offset_mm, name="PROBE PLANE"
    )
    sketch.create_sketch("Front Plane")
    sketch.circle(0.0, 0.0, 5.0)
    sketch.exit_sketch()
    return doc


def probe_offset_from_surface():
    results = []
    for label, translate in [("translate_false", False), ("translate_true", True)]:
        doc = _plane_sketch("offset2_" + label)
        session.clear_selection(doc)
        session.select_sketch(doc, "Sketch1", append=False, mark=0)
        session.select_plane(doc, "PROBE PLANE", mark=1, append=True)
        info = {"case": label}
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc, t=translate: doc.FeatureManager.FeatureExtrusion3(
                    *_extrude_args(5, 5.0, translate_surface=t)
                ),
            )
        )
        results.append(info)
    return results


def probe_up_to_body():
    results = []
    for body_mark in (1, 0):
        doc = new_part(f"upto_body_m{body_mark}")
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
        sketch.create_sketch("Front Plane")
        sketch.circle(0.0, 0.0, 5.0)
        sketch.exit_sketch()
        info: dict = {"case": f"body_mark={body_mark}"}
        session.clear_selection(doc)
        session.select_sketch(doc, "Sketch3", append=False, mark=0)
        target = inspect._bodies(doc)[0]  # the block
        data = inspect.create_select_data(doc, body_mark)
        selected = False
        try:
            selected = bool(target.Select2(True, data))
        except Exception as exc:  # noqa: BLE001
            info["body_select_error"] = f"{type(exc).__name__}: {exc}"
        info["body_selected"] = selected
        info.update(
            attempt(
                doc,
                "upto_body",
                lambda doc=doc: doc.FeatureManager.FeatureExtrusion3(
                    *_extrude_args(7, 0.0)
                ),
            )
        )
        results.append(info)
    return results


def probe_chamfer_equal_distance():
    results = []
    cases = [
        ("t16_w10_other10", 4, 16, 10.0, 0.0, 10.0),
        ("t16_w0_other10", 4, 16, 0.0, 0.0, 10.0),
        ("t16_w10_other0_opt1", 1, 16, 10.0, 0.0, 0.0),
        ("t1_w10_a45_other0", 4, 1, 10.0, 45.0, 0.0),
    ]
    for label, options, ctype, width, angle, other in cases:
        doc = new_part("chamfer2_" + label)
        sketch.create_sketch("Front Plane")
        sketch.rectangle(-20.0, -20.0, 20.0, 20.0)
        sketch.exit_sketch()
        features.boss_extrude(depth_mm=40.0)
        before = volume_mm3(doc)
        edge = None
        for item in inspect.list_edges(doc):
            if item.get("curve") != "line":
                continue
            start, end = item.get("start_mm") or [], item.get("end_mm") or []
            if (
                len(start) >= 3
                and len(end) >= 3
                and abs(start[2] - 40.0) < 0.01
                and abs(end[2] - 40.0) < 0.01
            ):
                edge = item["index"]
                break
        info = {"case": label, "before_volume_mm3": before, "edge": edge}
        if edge is None:
            results.append({**info, "error": "no edge"})
            continue
        session.clear_selection(doc)
        inspect.select_edges(doc, [edge], append=False)
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc, o=options, c=ctype, w=width, a=angle, d=other: (
                    doc.FeatureManager.InsertFeatureChamfer(
                        o, c, units.mm_to_m(w), units.deg_to_rad(a),
                        units.mm_to_m(d), 0.0, 0.0, 0.0,
                    )
                ),
            )
        )
        if before is not None and info.get("volume_mm3") is not None:
            info["removed_mm3"] = round(before - info["volume_mm3"], 4)
        results.append(info)
    return results


def probe_variable_fillet_readback():
    doc = new_part("varfillet_readback")
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-20.0, -20.0, 20.0, 20.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=40.0)
    edge = None
    for item in inspect.list_edges(doc):
        if item.get("curve") != "line":
            continue
        start, end = item.get("start_mm") or [], item.get("end_mm") or []
        if (
            len(start) >= 3
            and len(end) >= 3
            and abs(start[2] - 40.0) < 0.01
            and abs(end[2] - 40.0) < 0.01
        ):
            edge = item["index"]
            break
    session.clear_selection(doc)
    inspect.select_edges(doc, [edge], append=False)
    feature = doc.FeatureManager.FeatureFillet3(
        7, units.mm_to_m(5.0), 0.0, 0.0, 1, 0, 0,
        [units.mm_to_m(3.0), units.mm_to_m(8.0)],
        None, None, None, None, None, None,
    )
    inspect.rebuild(doc)
    info: dict = {}
    if feature is None:
        return {"error": "variable fillet did not build"}
    wrapped = binding.wrap(feature, "IFeature")
    info["name"] = str(binding.value(wrapped.Name))
    info["type"] = str(wrapped.GetTypeName2())
    try:
        definition = binding.wrap(
            wrapped.GetDefinition(), "IVariableFilletFeatureData2"
        )
        info["default_radius_mm"] = round(
            units.m_to_mm(float(binding.value(definition.DefaultRadius))), 4
        )
        info["edge_count"] = int(definition.FilletEdgeCount)
        info["control_points"] = int(definition.GetControlPointsCount())
        for index in range(info["control_points"]):
            try:
                radius = float(definition.GetControlPointRadiusAtIndex(index, None, None))
                info.setdefault("control_point_radii_mm", []).append(
                    round(units.m_to_mm(radius), 4)
                )
            except Exception as exc:  # noqa: BLE001
                info.setdefault("control_point_errors", []).append(
                    f"{index}: {type(exc).__name__}: {exc}"
                )
    except Exception as exc:  # noqa: BLE001
        info["definition_error"] = f"{type(exc).__name__}: {exc}"
    return info


def probe_cosmetic_thread_tree():
    doc = new_part("thread_tree")
    sketch.create_sketch("Front Plane")
    sketch.rectangle(-10.0, -10.0, 10.0, 10.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=20.0)
    top = find_face(doc, "+z")
    features.simple_hole(6.0, top, 10.0, 10.0, end_condition="through_all")
    circle = None
    for edge in inspect.list_edges(doc):
        if edge.get("curve") == "circle" and abs(
            edge.get("length_mm", 0) - math.pi * 6
        ) < 0.1:
            circle = edge["index"]
            break
    session.clear_selection(doc)
    inspect.select_edges(doc, [circle], append=False)
    returned = doc.FeatureManager.InsertCosmeticThread2(
        0, units.mm_to_m(15.0), units.mm_to_m(15.0), "M6x1"
    )
    inspect.rebuild(doc)
    info: dict = {"circle_edge": circle, "returned_none": returned is None}
    if returned is not None:
        wrapped = binding.wrap(returned, "IFeature")
        info["returned_name"] = str(binding.value(wrapped.Name))
        info["returned_type"] = str(wrapped.GetTypeName2())
        try:
            definition = binding.wrap(
                wrapped.GetDefinition(), "ICosmeticThreadFeatureData"
            )
            info["thread_data"] = {
                "diameter_mm": round(
                    units.m_to_mm(float(binding.value(definition.Diameter))), 4
                ),
                "depth_mm": round(
                    units.m_to_mm(float(binding.value(definition.Depth))), 4
                ),
                "callout": str(binding.value(definition.ThreadCallout) or ""),
            }
        except Exception as exc:  # noqa: BLE001
            info["definition_error"] = f"{type(exc).__name__}: {exc}"
    # Walk the whole tree including sub-features.
    tree = []

    def walk(feature, depth):
        current = feature
        while current:
            wrapped = binding.wrap(current, "IFeature")
            try:
                tree.append(
                    {
                        "depth": depth,
                        "name": str(binding.value(wrapped.Name)),
                        "type": str(wrapped.GetTypeName2()),
                    }
                )
            except Exception:
                pass
            try:
                walk(wrapped.GetFirstSubFeature(), depth + 1)
            except Exception:
                pass
            current = wrapped.GetNextFeature()

    walk(doc.FirstFeature(), 0)
    info["tree"] = tree
    info["whats_wrong"] = inspect.whats_wrong(doc)
    return info


def probe_dome():
    results = []
    trials = [
        ("box_top_m0", "box", 0, False),
        ("box_top_m1", "box", 1, False),
        ("cyl_top_m0", "cylinder", 0, False),
        ("cyl_top_m1", "cylinder", 1, False),
        ("cyl_top_m0_ell", "cylinder", 0, True),
    ]
    for label, shape, mark, elliptic in trials:
        print(f"  dome trial: {label}", flush=True)
        doc = new_part("dome2_" + label)
        if shape == "box":
            sketch.create_sketch("Front Plane")
            sketch.rectangle(-20.0, -20.0, 20.0, 20.0)
            sketch.exit_sketch()
            features.boss_extrude(depth_mm=20.0)
        else:
            sketch.create_sketch("Front Plane")
            sketch.circle(0.0, 0.0, 20.0)
            sketch.exit_sketch()
            features.boss_extrude(depth_mm=30.0)
        top = find_face(doc, "+z")
        before = volume_mm3(doc)
        session.clear_selection(doc)
        inspect.select_faces(doc, [top], append=False, mark=mark)
        info = {"case": label, "top": top, "before_volume_mm3": before}
        info.update(
            attempt(
                doc,
                label,
                lambda doc=doc, e=elliptic: doc.InsertDome(
                    units.mm_to_m(10.0), False, e
                ),
            )
        )
        if before is not None and info.get("volume_mm3") is not None:
            info["added_mm3"] = round(info["volume_mm3"] - before, 4)
        results.append(info)
    return results


def main() -> int:
    global APPLICATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="run a single probe by name")
    args = parser.parse_args()

    APPLICATION = session.app()

    probes = [
        ("offset_from_surface", probe_offset_from_surface),
        ("up_to_body", probe_up_to_body),
        ("chamfer_equal_distance", probe_chamfer_equal_distance),
        ("variable_fillet_readback", probe_variable_fillet_readback),
        ("cosmetic_thread_tree", probe_cosmetic_thread_tree),
        ("dome", probe_dome),
    ]
    for name, fn in probes:
        if args.only and name != args.only:
            continue
        probe(name, fn)

    # Belt-and-braces: anything a single probe_fn created but did not close.
    close_created_since(0)

    print(json.dumps({"probes": RESULTS}, indent=2, default=str))
    failed = [item for item in RESULTS if not item["ok"]]
    print(f"\nPROBE: {len(RESULTS) - len(failed)}/{len(RESULTS)} completed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
