#!/usr/bin/env python
"""Positive control: direct IInsertCombineFeature subtraction call.

Runs one fresh scratch part, selects both overlapping prisms, and makes one
IFeatureManager.IInsertCombineFeature call. The document is discarded.
"""
from __future__ import annotations

import json
import math

import pythoncom

from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.com import binding
from solidworks_mcp.domain import documents, features, inspect, session, sketch

OPERATION = "subtract"
OPERATION_CODE = 15902
PRISMS = (
    (0.0, 10.0, 0.0, 10.0, 10.0),
    (5.0, 15.0, 2.0, 12.0, 12.0),
)


def _type_name(obj) -> str:
    return f"{type(obj).__module__}.{type(obj).__name__}"


def _box_volume(record: dict) -> float:
    box = record["box_mm"]
    return math.prod(box["max"][axis] - box["min"][axis] for axis in range(3))


def probe() -> dict:
    opened = False
    result = {"operation": OPERATION, "operation_code": OPERATION_CODE}
    try:
        documents.new_document("part")
        opened = True
        for x0, x1, y0, y1, depth in PRISMS:
            sketch.create_sketch("front")
            sketch.rectangle(x0, y0, x1, y1)
            sketch.exit_sketch()
            features.boss_extrude(depth_mm=depth, merge=False)

        _, doc, _ = session.active_doc(("part",))
        bodies = inspect._bodies(doc)
        source_records = inspect.list_bodies(doc)
        if len(bodies) != 2:
            raise RuntimeError(f"expected 2 source bodies, got {len(bodies)}")
        box_a, box_b = (record["box_mm"] for record in source_records)
        overlap = math.prod(
            max(
                0.0,
                min(box_a["max"][axis], box_b["max"][axis])
                - max(box_a["min"][axis], box_b["min"][axis]),
            )
            for axis in range(3)
        )
        expected = _box_volume(source_records[0]) - overlap
        before_names = sorted(features.feature_names(doc))
        selected_count = inspect.select_bodies(doc, [0, 1])
        fm = binding.wrap(doc.FeatureManager, "IFeatureManager")
        tool_body = binding.wrap(bodies[1], "IBody2")
        result.update(
            {
                "selected_body_count": selected_count,
                "manager_wrapper_type": _type_name(fm),
                "body_wrapper_type": _type_name(tool_body),
            }
        )

        feature = fm.IInsertCombineFeature(
            OPERATION_CODE, bodies[0], 1, tool_body
        )
        after_names = sorted(features.feature_names(doc))
        rebuild = inspect.rebuild(doc)
        after_bodies = inspect.list_bodies(doc)
        mass = inspect.mass_properties(doc)
        wrong = inspect.whats_wrong(doc)
        actual = mass.get("volume_mm3")
        result.update(
            {
                "feature_returned": feature is not None,
                "feature_tree_before": before_names,
                "feature_tree_after_call": after_names,
                "new_feature_names": [name for name in after_names if name not in before_names],
                "rebuild": rebuild,
                "whats_wrong": wrong,
                "body_count": len(after_bodies),
                "volume_mm3": actual,
                "expected_volume_mm3": expected,
                "volume_error_mm3": None if actual is None else actual - expected,
                "volume_pass": (
                    actual is not None
                    and abs(actual - expected) <= max(0.05, expected * 1e-4)
                ),
                "source_bodies": source_records,
                "bodies_after": after_bodies,
            }
        )
    except pythoncom.com_error as exc:
        args = exc.args
        result["com_error"] = {
            "hresult": args[0] if len(args) > 0 else None,
            "text": args[1] if len(args) > 1 else str(exc),
            "excepinfo": args[2] if len(args) > 2 else None,
            "argerror": args[3] if len(args) > 3 else None,
        }
        result["stopped_on_com_error"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["stopped_on_error"] = True
    finally:
        if opened:
            documents.close_document(save=False)
    return result


if __name__ == "__main__":
    worker = ComWorker()
    set_worker(worker)
    worker.start()
    try:
        print(json.dumps(run(probe), indent=2, default=str))
    finally:
        worker.stop()
