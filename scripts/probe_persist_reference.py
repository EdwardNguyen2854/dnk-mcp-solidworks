#!/usr/bin/env python
"""Selection-reference identity probe: entity identity via persist references.

Measures, against the running SOLIDWORKS session (never launching it):

- reading the engineer's current selection through ``ISelectionMgr``;
- ``GetPersistReference3`` / ``GetObjectByPersistReference3`` round-trips;
- whether references survive save + close + reopen in a new session;
- whether they survive a later topology-changing rebuild;
- what happens when the referenced face itself is consumed by a feature;
- what geometric fingerprint data is available as a fallback and how
  ambiguous a fingerprint match is on a real part.

The script creates its own scratch part, saves it under the configured output
root, and deletes it unless ``--keep`` is passed. The engineer's open documents
stay open, but this script does change which document is active.

Usage:
    python scripts/probe_persist_reference.py [--keep]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from solidworks_mcp import registry  # noqa: E402
from solidworks_mcp.com import binding  # noqa: E402
from solidworks_mcp.com.worker import ComWorker, run, set_worker  # noqa: E402
from solidworks_mcp.config import load_config  # noqa: E402
from solidworks_mcp.domain import inspect, session  # noqa: E402
from solidworks_mcp.tools import core as _core  # noqa: E402,F401 - registers tools
from solidworks_mcp.tools import extended as _extended  # noqa: E402,F401

INTERFACES = {"face": "IFace2", "edge": "IEdge", "vertex": "IVertex"}
DESCRIBERS = {
    "face": inspect.face_details,
    "edge": inspect.edge_details,
    "vertex": inspect.vertex_details,
}
# swSelectType_e values for the topology kinds this probe cares about.
SELECT_TYPE_KIND = {1: "edge", 2: "face", 3: "vertex"}
# A cheap member that only succeeds on the matching interface; QueryInterface
# alone can succeed for a neighbouring topology type, so probe a real member.
PROBE_MEMBERS = {"face": "GetArea", "edge": "GetCurve", "vertex": "GetPoint"}

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def tool(tool_name: str, **args) -> dict:
    envelope = registry.invoke(tool_name, args)
    if not envelope.get("ok"):
        raise RuntimeError(f"{tool_name} failed: {json.dumps(envelope.get('error'))}")
    return envelope.get("data", {})


def text_of(reference) -> bytes | None:
    """Normalise the VARIANT returned by GetPersistReference3 to bytes."""
    if reference is None:
        return None
    if isinstance(reference, (tuple, list)):
        reference = reference[0] if reference else None
    if reference is None:
        return None
    if isinstance(reference, bytes):
        return reference
    if isinstance(reference, str):
        return reference.encode("latin-1")
    try:
        return bytes(bytearray(reference))
    except Exception:
        return None


def describe(entity) -> tuple[str | None, dict]:
    """Describe a raw entity by probing an interface-specific member.

    QueryInterface alone can succeed for a neighbouring topology type, so the
    kind is decided by calling a member only that interface answers.
    """
    for kind, interface in INTERFACES.items():
        try:
            wrapped = binding.wrap(entity, interface)
            member = getattr(wrapped, PROBE_MEMBERS[kind])
            value = binding.value(member)
            if value is None:
                continue
            return kind, DESCRIBERS[kind](wrapped)
        except Exception:
            continue
    return None, {}


def read_selection() -> dict:
    """Selection snapshot from ISelectionMgr on the COM thread."""

    def job() -> dict:
        _, doc, _ = session.active_doc(("part",))
        manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
        count = int(binding.value(manager.GetSelectedObjectCount2(-1)) or 0)
        items = []
        for index in range(1, count + 1):
            entity = manager.GetSelectedObject6(index, -1)
            if entity is None:
                continue
            select_type = int(
                binding.value(manager.GetSelectedObjectType3(index, -1)) or -1
            )
            kind = SELECT_TYPE_KIND.get(select_type)
            details: dict = {}
            if kind is not None:
                try:
                    details = DESCRIBERS[kind](binding.wrap(entity, INTERFACES[kind]))
                except Exception:
                    kind, details = describe(entity)
            else:
                kind, details = describe(entity)
            items.append(
                {
                    "kind": kind,
                    "select_type": select_type,
                    "mark": int(binding.value(manager.GetSelectedObjectMark(index)) or 0),
                    "details": details,
                    "raw": entity,
                }
            )
        return {"document": session.doc_info(doc), "count": count, "items": items}

    return run(job)


def select_probe_entities() -> dict:
    """Select the top face and the first edge for the reference probe."""

    def job() -> dict:
        _, doc, _ = session.active_doc(("part",))
        faces = inspect.list_faces(doc)
        top = next(face for face in faces if face.get("normal") == [0.0, 0.0, 1.0])
        edges = inspect.list_edges(doc)
        inspect.select_faces(doc, [top["index"]])
        inspect.select_edges(doc, [edges[0]["index"]], append=True)
        return {"top": top, "edge": edges[0] if edges else None}

    return run(job)


def capture_reference(entity) -> dict:
    """Persist reference for a raw selected entity, plus a resolved re-read."""

    def job() -> dict:
        _, doc, _ = session.active_doc(("part",))
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
        raw = extension.GetPersistReference3(entity)
        reference = text_of(raw)
        result: dict = {
            "bytes": len(reference) if reference else 0,
            "raw_type": type(raw).__name__,
            "reference": reference,
        }
        if not reference:
            return result
        resolved, out = session.com_result(
            extension.GetObjectByPersistReference3(reference, 0), 1
        )
        result["error_code"] = out[0] if out else None
        result["resolved"] = resolved is not None
        if resolved is not None:
            kind, details = describe(resolved)
            result["resolved_kind"] = kind
            result["resolved_details"] = details
            second = text_of(extension.GetPersistReference3(resolved))
            if second:
                result["same_id"] = bool(extension.IsSamePersistentID(reference, second))
        return result

    return run(job)


def resolve_reference(reference: bytes) -> dict:
    """Resolve a captured reference against whatever document is active now."""

    def job() -> dict:
        _, doc, _ = session.active_doc(("part",))
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
        resolved, out = session.com_result(
            extension.GetObjectByPersistReference3(reference, 0), 1
        )
        result = {"error_code": out[0] if out else None, "resolved": resolved is not None}
        if resolved is not None:
            kind, details = describe(resolved)
            result["kind"] = kind
            result["details"] = details
            second = text_of(extension.GetPersistReference3(resolved))
            if second:
                result["same_id"] = bool(extension.IsSamePersistentID(reference, second))
        return result

    return run(job)


def fingerprint_matches(kind: str, details: dict) -> int:
    """How many current entities match the captured fingerprint?"""

    def job() -> int:
        _, doc, _ = session.active_doc(("part",))
        if kind == "face":
            candidates = inspect.list_faces(doc)
            return sum(1 for item in candidates if _face_matches(item, details))
        if kind == "edge":
            candidates = inspect.list_edges(doc)
            return sum(1 for item in candidates if _edge_matches(item, details))
        return 0

    return run(job)


def face_index_by_fingerprint(details: dict) -> int | None:
    """Index of the unique current face matching the fingerprint, or None."""

    def job() -> int | None:
        _, doc, _ = session.active_doc(("part",))
        matches = [face for face in inspect.list_faces(doc) if _face_matches(face, details)]
        return matches[0]["index"] if len(matches) == 1 else None

    return run(job)


def _face_matches(candidate: dict, details: dict) -> bool:
    if candidate.get("surface") != details.get("surface"):
        return False
    area = details.get("area_mm2")
    if area is not None and abs(float(candidate.get("area_mm2", -1)) - float(area)) > 1e-3:
        return False
    normal = details.get("normal")
    if normal is not None:
        other = candidate.get("normal")
        if not other or sum(a * b for a, b in zip(normal, other)) < 0.9999:
            return False
    box = details.get("box_mm")
    if box is not None and candidate.get("box_mm") is not None:
        for key in ("min", "max"):
            for a, b in zip(box[key], candidate["box_mm"][key]):
                if abs(float(a) - float(b)) > 0.05:
                    return False
    return True


def _edge_matches(candidate: dict, details: dict) -> bool:
    if candidate.get("curve") != details.get("curve"):
        return False
    length = details.get("length_mm")
    if length is not None and abs(float(candidate.get("length_mm", -1)) - float(length)) > 1e-3:
        return False
    for key in ("start_mm", "end_mm", "center_mm"):
        expected, other = details.get(key), candidate.get(key)
        if expected is not None and other is not None:
            if sum(abs(float(a) - float(b)) for a, b in zip(expected, other)) > 0.05:
                return False
    return True


def summary(result: dict) -> str:
    """A compact, JSON-safe view of a capture/resolve result."""
    return json.dumps(
        {key: value for key, value in result.items() if key != "reference"}
    )[:240]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the scratch part")
    options = parser.parse_args()

    config = load_config()
    worker = ComWorker(timeout=config.operation_timeout_sec)
    worker.start()
    set_worker(worker)

    scratch = config.output_root / "datum-persist-spike.SLDPRT"
    try:
        tool("new_document", kind="part")
        tool("create_sketch", plane="front")
        tool("sketch_rectangle", x1_mm=-50, y1_mm=-30, x2_mm=50, y2_mm=30)
        tool("exit_sketch")
        tool("boss_extrude", depth_mm=25, name="Base")

        # 1. Read the engineer's current selection.
        probe = select_probe_entities()
        selection = read_selection()
        check(
            "selection read reports both entities with types and marks",
            selection["count"] == 2
            and {item["select_type"] for item in selection["items"]} == {1, 2},
            json.dumps(
                [
                    {"kind": item["kind"], "type": item["select_type"], "mark": item["mark"]}
                    for item in selection["items"]
                ]
            ),
        )
        check(
            "selection read carries fingerprint details",
            all(item["details"] for item in selection["items"]),
            json.dumps([item["details"] for item in selection["items"]])[:220],
        )

        # 2. Persist-reference round trip on the current selection.
        by_kind = {item["kind"]: item for item in selection["items"]}
        face_ref = capture_reference(by_kind["face"]["raw"])
        check(
            "GetPersistReference3 returns bytes and resolves immediately",
            face_ref["bytes"] > 0
            and face_ref.get("resolved") is True
            and face_ref.get("error_code") == 0,
            summary(face_ref),
        )
        check(
            "resolved reference reports the same persistent id",
            face_ref.get("same_id") is True,
            f"same_id={face_ref.get('same_id')} raw_type={face_ref['raw_type']}",
        )
        edge_ref = capture_reference(by_kind["edge"]["raw"])
        check(
            "edge reference round-trips too",
            edge_ref.get("resolved") is True and edge_ref.get("same_id") is True,
            summary(edge_ref),
        )

        # 3. Save, close, and reopen in a new document session.
        tool("save_document", path=str(scratch), overwrite=True)
        tool("close_document", save=False)
        tool("open_document", path=str(scratch))

        top_reopen = resolve_reference(face_ref["reference"])
        check(
            "top-face reference survives save/reopen",
            top_reopen.get("resolved") is True and top_reopen.get("same_id") is True,
            summary(top_reopen),
        )
        edge_reopen = resolve_reference(edge_ref["reference"])
        check(
            "edge reference survives save/reopen",
            edge_reopen.get("resolved") is True and edge_reopen.get("same_id") is True,
            summary(edge_reopen),
        )
        face_fp = fingerprint_matches("face", face_ref.get("resolved_details", {}))
        check(
            "face fingerprint is unique after reopen",
            face_fp == 1,
            f"matches={face_fp}",
        )
        edge_fp = fingerprint_matches("edge", probe["edge"])
        check(
            "edge fingerprint match count measured after reopen",
            edge_fp >= 1,
            f"matches={edge_fp}",
        )

        # 4. Topology-changing rebuild: a disjoint second body from the front plane.
        tool("create_sketch", plane="front")
        tool("sketch_rectangle", x1_mm=60, y1_mm=-10, x2_mm=80, y2_mm=10)
        tool("exit_sketch")
        tool("boss_extrude", depth_mm=10, name="SideBoss", merge=False)
        features = tool("list_features")
        check(
            "topology change built (disjoint body)",
            any(item.get("name") == "SideBoss" for item in features.get("features", [])),
            "SideBoss extruded as a second body",
        )
        top_rebuilt = resolve_reference(face_ref["reference"])
        check(
            "top-face reference survives a topology-changing rebuild",
            top_rebuilt.get("resolved") is True and top_rebuilt.get("same_id") is True,
            summary(top_rebuilt),
        )

        # 5. Modify the referenced face itself: through-cut a hole in it.
        before_volume = float(tool("get_mass_properties").get("volume_mm3", -1))
        face_index = face_index_by_fingerprint(face_ref.get("resolved_details", {}))
        check(
            "fingerprint fallback re-finds the referenced face uniquely",
            face_index is not None,
            f"index={face_index}",
        )
        tool("create_sketch", face_index=face_index)
        tool("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
        tool("exit_sketch")
        tool("cut_extrude", end_condition="through_all", name="TopCut")
        features = tool("list_features")
        check(
            "referenced-face modification built",
            any(item.get("name") == "TopCut" for item in features.get("features", [])),
            "through cut created on the referenced face",
        )
        after_volume = float(tool("get_mass_properties").get("volume_mm3", -1))
        check(
            "through cut removed material",
            after_volume < before_volume - 1000.0,
            f"volume {before_volume:.0f} -> {after_volume:.0f} mm3",
        )
        consumed = resolve_reference(face_ref["reference"])
        check(
            "a changed referenced face still resolves to the same entity",
            consumed.get("resolved") is True and consumed.get("same_id") is True,
            summary(consumed),
        )
        changed_area = consumed.get("details", {}).get("area_mm2")
        check(
            "resolved face reflects the modification (hole removes area)",
            isinstance(changed_area, (int, float)) and float(changed_area) < 6000.0,
            f"area_mm2={changed_area} (was 6000.0)",
        )

        reopened = read_selection()
        check(
            "reopened document starts with an empty selection",
            reopened["count"] == 0,
            f"count={reopened['count']}",
        )
    except Exception as error:  # noqa: BLE001 - spike reports and exits
        check("spike completed without exception", False, f"{type(error).__name__}: {error}")
    finally:
        try:
            tool("close_document", save=False)
        except Exception:
            pass
        if not options.keep:
            try:
                scratch.unlink(missing_ok=True)
            except OSError as error:
                print(f"could not delete {scratch}: {error}")
        worker.stop()

    failed = [name for name, passed, _ in CHECKS if not passed]
    print()
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        print("failed: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
