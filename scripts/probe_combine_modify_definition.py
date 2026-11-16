#!/usr/bin/env python
"""Test CombineBodiesFeatureData OperationType via ModifyDefinition.

Each operation gets a fresh part, creates a subtraction Combine1 via the
verified IPartDoc path, changes only OperationType, and calls ModifyDefinition
once. No AccessSelections/ReleaseSelectionAccess or retries are used.
"""
from __future__ import annotations

import json
import math

import pythoncom
import win32com.client

from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.com import binding
from solidworks_mcp.domain import documents, features, inspect, session, sketch

OPS = (("add", 0, 1800.0), ("common", 2, 400.0))
PRISMS = (
    (0.0, 10.0, 0.0, 10.0, 10.0),
    (5.0, 15.0, 2.0, 12.0, 12.0),
)


def _error_record(exc: Exception) -> dict:
    record = {"type": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, pythoncom.com_error):
        args = exc.args
        record.update(
            {
                "hresult": args[0] if len(args) > 0 else None,
                "text": args[1] if len(args) > 1 else str(exc),
                "excepinfo": args[2] if len(args) > 2 else None,
                "argerror": args[3] if len(args) > 3 else None,
            }
        )
    return record


def _box_volume(record: dict) -> float:
    box = record["box_mm"]
    return math.prod(box["max"][axis] - box["min"][axis] for axis in range(3))


def _probe_one(operation: str, operation_type: int, expected: float) -> dict:
    opened = False
    result = {"operation": operation, "operation_type": operation_type}
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
        overlap = math.prod(
            max(
                0.0,
                min(source_records[0]["box_mm"]["max"][axis], source_records[1]["box_mm"]["max"][axis])
                - max(source_records[0]["box_mm"]["min"][axis], source_records[1]["box_mm"]["min"][axis]),
            )
            for axis in range(3)
        )
        volume_a = _box_volume(source_records[0])
        expected_subtract = volume_a - overlap
        if abs(expected_subtract - 800.0) > 1e-6:
            raise RuntimeError(f"fixture expected subtraction 800 mm3, got {expected_subtract}")

        selected_count = inspect.select_bodies(doc, [0, 1])
        part = binding.wrap(doc, "IPartDoc")
        main_body = binding.wrap(bodies[0], "IBody2")
        tool_body = binding.wrap(bodies[1], "IBody2")
        tool_var = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [tool_body]
        )
        inserted = part.InsertCombineFeature(15902, main_body, tool_var)
        if not inserted:
            raise RuntimeError("subtraction setup InsertCombineFeature returned False")

        feature = next(
            (
                item
                for item in session.iter_features(doc)
                if str(binding.value(item.Name) or "") == "Combine1"
            ),
            None,
        )
        if feature is None:
            raise RuntimeError("Combine1 not found by session.iter_features")
        before_names = sorted(features.feature_names(doc))
        definition = binding.wrap(feature.GetDefinition(), "ICombineBodiesFeatureData")
        # Change only OperationType; deliberately do not access selections.
        definition.OperationType = operation_type
        modify_result = feature.ModifyDefinition(definition, doc, None)
        after_names = sorted(features.feature_names(doc))
        rebuild = inspect.rebuild(doc)
        after_bodies = inspect.list_bodies(doc)
        mass = inspect.mass_properties(doc)
        wrong = inspect.whats_wrong(doc)
        actual = mass.get("volume_mm3")
        result.update(
            {
                "selected_body_count": selected_count,
                "insert_subtraction_result": inserted,
                "feature_type_name": str(feature.GetTypeName2()),
                "definition_wrapper_type": f"{type(definition).__module__}.{type(definition).__name__}",
                "modify_result": modify_result,
                "feature_tree_before_modify": before_names,
                "feature_tree_after_modify": after_names,
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
                "access_selections_called": False,
                "release_selection_access_called": False,
            }
        )
    except Exception as exc:
        result["error"] = _error_record(exc)
        result["stopped_on_error"] = True
        raise
    finally:
        if opened:
            documents.close_document(save=False)
    return result


def probe() -> dict:
    results = {}
    for operation, operation_type, expected in OPS:
        try:
            results[operation] = _probe_one(operation, operation_type, expected)
        except Exception as exc:
            if operation not in results:
                results[operation] = {
                    "operation": operation,
                    "operation_type": operation_type,
                    "error": _error_record(exc),
                }
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
