#!/usr/bin/env python
"""Live probe #3: the last Wave-1 questions.

1. Cosmetic thread read-back through ICosmeticThreadFeatureData: which
   members carry the inserted values, and does the feature report clean?
2. Variable-radius fillet semantics: compare radii arrays [5,5] vs [5] vs
   [8,3] against the constant-fillet removal, and try the per-edge read-back.
3. offset-from-surface with OffsetReverse1=True: does the offset extend past
   the reference surface (35 mm) or cut back (25 mm)?
4. InsertDome on a second, careful attempt is skipped here because the last
   run hung inside it - it gets its own opt-in script.

Scratch parts only; each probe closes its own documents.
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
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(
            {
                "probe": name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4),
            }
        )
    close_created_since(created_before)
    print(f"[probe] {name}: {json.dumps(RESULTS[-1], default=str)[:900]}", flush=True)
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


def top_edge(doc, height_mm: float):
    for item in inspect.list_edges(doc):
        if item.get("curve") != "line":
            continue
        start, end = item.get("start_mm") or [], item.get("end_mm") or []
        if (
            len(start) >= 3
            and len(end) >= 3
            and abs(start[2] - height_mm) < 0.01
            and abs(end[2] - height_mm) < 0.01
        ):
            return item["index"]
    return None


def cube_part(label, size=40.0):
    doc = new_part(label)
    sketch.create_sketch("Front Plane")
    half = size / 2
    sketch.rectangle(-half, -half, half, half)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=size)
    return doc


def find_face(doc, normal: str):
    for face in inspect.list_faces(doc, surface_type="plane", normal=normal):
        return face["index"]
    return None


# ---------------------------------------------------------------------------


def probe_fillet_radii_semantics():
    results = []
    cases = [
        ("constant_r5", None),
        ("radii_5_5", [5.0, 5.0]),
        ("radii_8_3", [8.0, 3.0]),
        ("radii_3_8", [3.0, 8.0]),
    ]
    for label, radii in cases:
        doc = cube_part("filletsem_" + label)
        before = volume_mm3(doc)
        edge = top_edge(doc, 40.0)
        session.clear_selection(doc)
        inspect.select_edges(doc, [edge], append=False)
        if radii is None:
            feature = doc.FeatureManager.FeatureFillet3(
                3, units.mm_to_m(5.0), 0.0, 0.0, 0, 0, 0,
                None, None, None, None, None, None, None,
            )
        else:
            feature = doc.FeatureManager.FeatureFillet3(
                7, units.mm_to_m(5.0), 0.0, 0.0, 1, 0, 0,
                [units.mm_to_m(value) for value in radii],
                None, None, None, None, None, None,
            )
        inspect.rebuild(doc)
        info = {"case": label, "before_volume_mm3": before}
        if feature is not None:
            wrapped = binding.wrap(feature, "IFeature")
            info["name"] = str(binding.value(wrapped.Name))
            try:
                definition = binding.wrap(
                    wrapped.GetDefinition(), "IVariableFilletFeatureData2"
                )
                item = definition.GetFilletEdgeAtIndex(0)
                info["edge_count"] = int(definition.FilletEdgeCount)
                info["default_radius_mm"] = round(
                    units.m_to_mm(float(binding.value(definition.DefaultRadius))), 4
                )
                info["edge_radius_mm"] = round(
                    units.m_to_mm(float(definition.GetRadius(item))), 4
                )
                info["control_points"] = int(definition.GetControlPointsCount())
            except Exception as exc:  # noqa: BLE001
                info["definition_error"] = f"{type(exc).__name__}: {exc}"
        else:
            info["feature_none"] = True
        info["volume_mm3"] = volume_mm3(doc)
        if before is not None and info["volume_mm3"] is not None:
            info["removed_mm3"] = round(before - info["volume_mm3"], 4)
        info["constant_r5_expected"] = round((1 - math.pi / 4) * 25 * 40, 3)
        results.append(info)
    return results


def probe_thread_readback():
    doc = new_part("thread_readback")
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
    info: dict = {
        "circle_edge": circle,
        "top_level_features": [f["name"] for f in session.list_feature_infos(doc)],
        "whats_wrong": inspect.whats_wrong(doc),
    }
    if returned is None:
        info["returned_none"] = True
        return info
    wrapped = binding.wrap(returned, "IFeature")
    info["name"] = str(binding.value(wrapped.Name))
    info["type"] = str(wrapped.GetTypeName2())
    definition = binding.wrap(wrapped.GetDefinition(), "ICosmeticThreadFeatureData")
    info["data"] = {
        "diameter_mm": round(
            units.m_to_mm(float(binding.value(definition.Diameter))), 4
        ),
        "blind_depth_mm": round(
            units.m_to_mm(float(binding.value(definition.BlindDepth))), 4
        ),
        "callout": str(binding.value(definition.ThreadCallout) or ""),
        "size": str(binding.value(definition.Size) or ""),
        "standard_type": str(binding.value(definition.StandardType) or ""),
        "apply_thread": int(binding.value(definition.ApplyThread)),
    }
    return info


def _extrude_args(t1, d1, translate_surface=False, offset_reverse=False):
    return (
        True, False, False, t1, 0,
        units.mm_to_m(d1), 0.0,
        False, False, False, False, 0.0, 0.0,
        bool(offset_reverse), False,
        bool(translate_surface), False,
        True, True, True, 0, 0.0, False,
    )


def probe_offset_reverse():
    results = []
    for label, reverse in [("reverse_false", False), ("reverse_true", True)]:
        doc = new_part("offset3_" + label)
        features.create_reference_plane(
            kind="offset", plane="Front Plane", distance_mm=30.0,
            name="PROBE PLANE",
        )
        sketch.create_sketch("Front Plane")
        sketch.circle(0.0, 0.0, 5.0)
        sketch.exit_sketch()
        session.clear_selection(doc)
        session.select_sketch(doc, "Sketch1", append=False, mark=0)
        session.select_plane(doc, "PROBE PLANE", mark=1, append=True)
        feature = doc.FeatureManager.FeatureExtrusion3(
            *_extrude_args(5, 5.0, offset_reverse=reverse)
        )
        inspect.rebuild(doc)
        info = {"case": label, "built": feature is not None}
        info["volume_mm3"] = volume_mm3(doc)
        try:
            info["bbox_mm"] = inspect.bounding_box(doc)
        except Exception as exc:  # noqa: BLE001
            info["bbox_error"] = f"{type(exc).__name__}: {exc}"
        results.append(info)
    return results


def probe_thread_semantics():
    doc = new_part("thread_semantics")
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
    # Distinct values tell Depth and Length apart.
    returned = doc.FeatureManager.InsertCosmeticThread2(
        0, units.mm_to_m(12.0), units.mm_to_m(7.0), "M8x1.25"
    )
    inspect.rebuild(doc)
    info: dict = {"returned_none": returned is None}
    if returned is not None:
        wrapped = binding.wrap(returned, "IFeature")
        definition = binding.wrap(wrapped.GetDefinition(), "ICosmeticThreadFeatureData")
        info["data"] = {
            "diameter_mm": round(
                units.m_to_mm(float(binding.value(definition.Diameter))), 4
            ),
            "blind_depth_mm": round(
                units.m_to_mm(float(binding.value(definition.BlindDepth))), 4
            ),
            "callout": str(binding.value(definition.ThreadCallout) or ""),
        }
        info["whats_wrong"] = inspect.whats_wrong(doc)
    return info


def main() -> int:
    global APPLICATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()
    APPLICATION = session.app()

    probes = [
        ("thread_readback", probe_thread_readback),
        ("thread_semantics", probe_thread_semantics),
        ("fillet_radii_semantics", probe_fillet_radii_semantics),
        ("offset_reverse", probe_offset_reverse),
    ]
    for name, fn in probes:
        if args.only and name != args.only:
            continue
        probe(name, fn)
    close_created_since(0)

    print(json.dumps({"probes": RESULTS}, indent=2, default=str))
    failed = [item for item in RESULTS if not item["ok"]]
    print(f"\nPROBE: {len(RESULTS) - len(failed)}/{len(RESULTS)} completed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
