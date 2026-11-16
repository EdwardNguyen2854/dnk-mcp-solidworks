#!/usr/bin/env python
"""Read back the definition of one verified subtraction combine feature.

Creates and discards one scratch part. Does not modify the feature definition
or call AccessSelections/ReleaseSelectionAccess.
"""
from __future__ import annotations

import json
import math

import pythoncom
import win32com.client

from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.com import binding
from solidworks_mcp.domain import documents, features, inspect, session, sketch

PRISMS = (
    (0.0, 10.0, 0.0, 10.0, 10.0),
    (5.0, 15.0, 2.0, 12.0, 12.0),
)


def _type_name(obj) -> str:
    return f"{type(obj).__module__}.{type(obj).__name__}"


def _box_volume(record: dict) -> float:
    box = record["box_mm"]
    return math.prod(box["max"][axis] - box["min"][axis] for axis in range(3))


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


def _read_value(definition, member_name: str) -> dict:
    try:
        member = getattr(definition, member_name)
        value = binding.value(member)
        if member_name == "MainBody" and value is not None:
            return {"value_type": _type_name(binding.wrap(value, "IBody2"))}
        if member_name == "BodiesToCombine" and value is not None:
            if not isinstance(value, (tuple, list)):
                values = [value]
            else:
                values = list(value)
            return {
                "container_type": _type_name(value),
                "count": len(values),
                "item_types": [
                    _type_name(binding.wrap(item, "IBody2")) for item in values
                ],
            }
        if isinstance(value, (str, int, float, bool)) or value is None:
            return {"value": value, "value_type": _type_name(value)}
        return {"value_repr": repr(value), "value_type": _type_name(value)}
    except Exception as exc:
        return {"error": _error_record(exc)}


def probe() -> dict:
    opened = False
    result = {"operation": "subtract", "operation_code": 15902}
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
        expected = _box_volume(source_records[0]) - overlap
        inspect.select_bodies(doc, [0, 1])
        part = binding.wrap(doc, "IPartDoc")
        main_body = binding.wrap(bodies[0], "IBody2")
        tool_body = binding.wrap(bodies[1], "IBody2")
        tool_var = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [tool_body]
        )
        api_result = part.InsertCombineFeature(15902, main_body, tool_var)

        feature = next(
            (
                item
                for item in session.iter_features(doc)
                if str(binding.value(item.Name) or "") == "Combine1"
            ),
            None,
        )
        result["combine_api_result"] = api_result
        result["combine_feature_found"] = feature is not None
        if feature is None:
            result["inspection_error"] = "Combine1 not found by session.iter_features"
            return result

        result["feature_type_name"] = str(feature.GetTypeName2())
        raw_definition = feature.GetDefinition()
        result["raw_definition_type"] = _type_name(raw_definition)
        definition = binding.wrap(raw_definition, "ICombineBodiesFeatureData")
        result["definition_wrapper_type"] = _type_name(definition)
        result["readback"] = {
            name: _read_value(definition, name)
            for name in (
                "OperationType",
                "MainBody",
                "GetBodiesToCombineCount",
                "BodiesToCombine",
            )
        }
        result["access_selections_called"] = False
        result["modify_definition_called"] = False
        result["expected_subtract_volume_mm3"] = expected
    except Exception as exc:
        result["error"] = _error_record(exc)
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
