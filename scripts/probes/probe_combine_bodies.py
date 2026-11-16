#!/usr/bin/env python
"""One-shot live probe for combine-body operation types on the attached session.

Creates two overlapping rectangular prisms in a scratch part for each
operation, checks rebuild and analytic volume, and closes without saving.
"""
from __future__ import annotations

import json
import math

import pythoncom
import win32com.client

from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.domain import documents, features, inspect, session, sketch

OPS = {"add": 15903, "subtract": 15902, "common": 15901}


def probe() -> dict:
    results = {}
    for operation, code in OPS.items():
        opened = False
        try:
            documents.new_document("part")
            opened = True
            for x0, x1, y0, y1, depth in (
                (0.0, 10.0, 0.0, 10.0, 10.0),
                (5.0, 15.0, 2.0, 12.0, 12.0),
            ):
                sketch.create_sketch("front")
                sketch.rectangle(x0, y0, x1, y1)
                sketch.exit_sketch()
                features.boss_extrude(depth_mm=depth, merge=False)

            _, doc, _ = session.active_doc(("part",))
            bodies = inspect._bodies(doc)
            source_records = inspect.list_bodies(doc)
            if len(bodies) != 2:
                raise RuntimeError(f"expected 2 source bodies, got {len(bodies)}")
            def box_volume(body_record):
                box = body_record["box_mm"]
                return math.prod(
                    box["max"][axis] - box["min"][axis] for axis in range(3)
                )
            boxes = [record["box_mm"] for record in source_records]
            overlap_lengths = [
                max(0.0, min(boxes[0]["max"][axis], boxes[1]["max"][axis])
                    - max(boxes[0]["min"][axis], boxes[1]["min"][axis]))
                for axis in range(3)
            ]
            overlap_volume = math.prod(overlap_lengths)
            main_volume, tool_volume = (box_volume(record) for record in source_records)
            expected_volume = {
                "add": main_volume + tool_volume - overlap_volume,
                "subtract": main_volume - overlap_volume,
                "common": overlap_volume,
            }[operation]
            tool_arrays = [
                ("tuple", (bodies[1],)),
                ("list", [bodies[1]]),
                (
                    "dispatch_array",
                    win32com.client.VARIANT(
                        pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [bodies[1]]
                    ),
                ),
            ]
            attempts = []
            feature = None
            for array_kind, tool_var in tool_arrays:
                feature = doc.FeatureManager.InsertCombineFeature(
                    code, bodies[0], tool_var
                )
                attempts.append({"tool_array": array_kind, "selected": False, "feature_returned": feature is not None})
                if feature is not None:
                    break
            if feature is None and operation != "subtract":
                feature = doc.FeatureManager.InsertCombineFeature(
                    code, bodies[0],
                    win32com.client.VARIANT(pythoncom.VT_DISPATCH, bodies[1]),
                )
                attempts.append({"tool_array": "single_dispatch", "selected": False, "feature_returned": feature is not None})
            if feature is None:
                feature = doc.FeatureManager.InsertCombineFeature(
                    code, bodies[1],
                    win32com.client.VARIANT(
                        pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [bodies[0]]
                    ),
                )
                attempts.append({"tool_array": "dispatch_array", "reversed_main_body": True, "selected": False, "feature_returned": feature is not None})
            if feature is None:
                inspect.select_bodies(doc, [0, 1])
                feature = doc.FeatureManager.InsertCombineFeature(
                    code, bodies[0], tool_arrays[2][1]
                )
                attempts.append({"tool_array": "dispatch_array", "selected": True, "feature_returned": feature is not None})
            rebuild = inspect.rebuild(doc)
            after_bodies = inspect.list_bodies(doc)
            mass = inspect.mass_properties(doc)
            wrong = inspect.whats_wrong(doc)
            actual = mass.get("volume_mm3")
            results[operation] = {
                "attempts": attempts,
                "rebuild": rebuild,
                "whats_wrong": wrong,
                "body_count": len(after_bodies),
                "volume_mm3": actual,
                "expected_volume_mm3": expected_volume,
                "volume_error_mm3": (
                    None if actual is None else actual - expected_volume
                ),
                "volume_pass": (
                    actual is not None
                    and abs(actual - expected_volume)
                    <= max(0.05, expected_volume * 1e-4)
                ),
                "bodies": after_bodies,
            }
        except Exception as exc:
            results[operation] = {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            if opened:
                documents.close_document(save=False)
    return results


if __name__ == "__main__":
    worker = ComWorker()
    set_worker(worker)
    worker.start()
    try:
        print(json.dumps(run(probe), indent=2, default=str))
    finally:
        worker.stop()
