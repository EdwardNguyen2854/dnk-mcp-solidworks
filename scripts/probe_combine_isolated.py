#!/usr/bin/env python
"""Isolate add/common combine calls in separate scratch parts.

Each operation gets one fresh document, one canonical typed tool array call,
and no retry variants. Documents are always discarded without saving.
"""
from __future__ import annotations

import json
import math

import pythoncom
import win32com.client

from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.domain import documents, features, inspect, session, sketch

OPS = (("add", 15903), ("common", 15901))
PRISMS = (
    (0.0, 10.0, 0.0, 10.0, 10.0),
    (5.0, 15.0, 2.0, 12.0, 12.0),
)


def _box_volume(record: dict) -> float:
    box = record["box_mm"]
    return math.prod(box["max"][axis] - box["min"][axis] for axis in range(3))


def _probe_one(operation: str, code: int) -> dict:
    opened = False
    result = {"operation": operation, "operation_code": code}
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
        overlap_volume = math.prod(
            max(
                0.0,
                min(box_a["max"][axis], box_b["max"][axis])
                - max(box_a["min"][axis], box_b["min"][axis]),
            )
            for axis in range(3)
        )
        volume_a, volume_b = (_box_volume(record) for record in source_records)
        expected = (
            volume_a + volume_b - overlap_volume
            if operation == "add"
            else overlap_volume
        )
        before_names = sorted(features.feature_names(doc))

        # No entities are preselected for this canonical MainBody/ToolVar call.
        session.clear_selection(doc)
        tool_var = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [bodies[1]]
        )
        feature = doc.FeatureManager.InsertCombineFeature(code, bodies[0], tool_var)
        after_call_names = sorted(features.feature_names(doc))
        rebuild = inspect.rebuild(doc)
        after_bodies = inspect.list_bodies(doc)
        mass = inspect.mass_properties(doc)
        wrong = inspect.whats_wrong(doc)
        actual = mass.get("volume_mm3")
        result.update(
            {
                "feature_returned": feature is not None,
                "feature_tree_before": before_names,
                "feature_tree_after_call": after_call_names,
                "new_feature_names": [
                    name for name in after_call_names if name not in before_names
                ],
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
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["stopped_after_error"] = True
        raise
    finally:
        if opened:
            documents.close_document(save=False)
    return result


def probe() -> dict:
    results = {}
    for operation, code in OPS:
        try:
            results[operation] = _probe_one(operation, code)
        except Exception as exc:
            # Stop at the first COM/probe failure; never try another call variant.
            results[operation] = {"operation": operation, "operation_code": code,
                                  "error": f"{type(exc).__name__}: {exc}"}
            break
    return results


if __name__ == "__main__":
    worker = ComWorker()
    set_worker(worker)
    worker.start()
    try:
        print(json.dumps(run(probe), indent=2, default=str))
    finally:
        worker.stop()
