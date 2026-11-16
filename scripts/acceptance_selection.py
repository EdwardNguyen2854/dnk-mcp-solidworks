#!/usr/bin/env python
"""Live acceptance for selection references and viewport highlight.

Drives the registered tools directly (same handlers the MCP server exposes)
against the running SOLIDWORKS session, and checks:

- get_selection returns bounded, labeled references for a face and an edge;
- resolve_entity_reference round-trips, survives save/reopen and a rebuild,
  and returns a refreshed reference;
- highlight_entities selects the referenced entities and clears again;
- a deleted entity fails as REFERENCE_NOT_FOUND;
- a reference from another document fails as REFERENCE_DOCUMENT_MISMATCH;
- the referenced face's changed geometry is reflected after a through cut.

Creates its own scratched part, saves it under the configured output root, and
deletes it unless ``--keep`` is passed.

Usage:
    python scripts/acceptance_selection.py [--keep]
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
from solidworks_mcp.com.worker import ComWorker, run, set_worker  # noqa: E402
from solidworks_mcp.config import load_config  # noqa: E402
from solidworks_mcp.domain import inspect, session  # noqa: E402
from solidworks_mcp.errors import SwMcpError  # noqa: E402
from solidworks_mcp.tools import core as _core  # noqa: E402,F401 - registers tools
from solidworks_mcp.tools import extended as _extended  # noqa: E402,F401

CHECKS: list[tuple[str, bool, str]] = []


def select_topology(face_index=None, edge_index=None) -> None:
    """Select probe entities on the COM thread."""

    def job() -> None:
        _, doc, _ = session.active_doc(("part",))
        first = True
        if face_index is not None:
            inspect.select_faces(doc, [face_index])
            first = False
        if edge_index is not None:
            inspect.select_edges(doc, [edge_index], append=not first)

    run(job)


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def invoke(tool_name: str, **args) -> dict:
    return registry.invoke(tool_name, args)


def data_of(tool_name: str, **args) -> dict:
    envelope = invoke(tool_name, **args)
    if not envelope.get("ok"):
        raise RuntimeError(f"{tool_name} failed: {json.dumps(envelope.get('error'))}")
    return envelope.get("data", {})


def error_code(tool_name: str, **args) -> str | None:
    """Error code for a failing tool, whether it raises or returns a failure."""
    try:
        envelope = invoke(tool_name, **args)
    except SwMcpError as error:
        return error.code
    if envelope.get("ok"):
        return None
    return (envelope.get("error") or {}).get("code")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the scratch part")
    options = parser.parse_args()

    config = load_config()
    worker = ComWorker(timeout=config.operation_timeout_sec)
    worker.start()
    set_worker(worker)

    scratch = config.output_root / "datum-selection-acceptance.SLDPRT"
    try:
        # Build a 100 x 60 x 25 box.
        data_of("new_document", kind="part")
        data_of("create_sketch", plane="front")
        data_of("sketch_rectangle", x1_mm=-50, y1_mm=-30, x2_mm=50, y2_mm=30)
        data_of("exit_sketch")
        data_of("boss_extrude", depth_mm=25, name="Base")
        # Establish the document identity before capturing references: saving
        # as a new name legitimately changes the scope, and references are
        # bound to the document they were captured in.
        data_of("save_document", path=str(scratch), overwrite=True)

        faces = inspect.list_faces()
        top = next(face for face in faces if face.get("normal") == [0.0, 0.0, 1.0])
        edges = inspect.list_edges()
        select_topology(face_index=top["index"], edge_index=edges[0]["index"])

        # 1. get_selection.
        selection = data_of("get_selection")
        kinds = {item["kind"] for item in selection.get("entities", [])}
        check(
            "get_selection returns the face and the edge",
            selection.get("count") == 2 and kinds == {"face", "edge"},
            json.dumps({"count": selection.get("count"), "kinds": sorted(kinds)}),
        )
        check(
            "get_selection entries carry ref, label, and measurements",
            all(item.get("ref") and item.get("label") for item in selection["entities"])
            and any(item.get("measurements") for item in selection["entities"]),
            json.dumps(
                [
                    {"kind": item["kind"], "label": item["label"], "measurements": item["measurements"]}
                    for item in selection["entities"]
                ]
            )[:240],
        )
        face_entry = next(item for item in selection["entities"] if item["kind"] == "face")
        edge_entry = next(item for item in selection["entities"] if item["kind"] == "edge")

        # 2. resolve_entity_reference round trip.
        resolved_face = data_of("resolve_entity_reference", ref=face_entry["ref"])
        check(
            "resolve returns the current index and refreshed reference",
            resolved_face.get("kind") == "face"
            and isinstance(resolved_face.get("index"), int)
            and bool(resolved_face.get("ref")),
            json.dumps({k: resolved_face.get(k) for k in ("kind", "index", "label")}),
        )
        refreshed = data_of("resolve_entity_reference", ref=resolved_face["ref"])
        check(
            "refreshed reference resolves to the same index",
            refreshed.get("index") == resolved_face.get("index"),
            f"index={refreshed.get('index')}",
        )
        data_of("resolve_entity_reference", ref=edge_entry["ref"])

        # 3. highlight and clear (owner-scoped lease).
        highlighted = data_of(
            "highlight_entities",
            refs=[face_entry["ref"], edge_entry["ref"]],
            owner="acceptance-highlight",
        )
        re_selected = data_of("get_selection")
        check(
            "highlight_entities selects both referenced entities",
            highlighted.get("highlighted") == 2 and re_selected.get("count") == 2,
            f"highlighted={highlighted.get('highlighted')} selected={re_selected.get('count')}",
        )
        cleared = data_of(
            "highlight_entities", refs=[], clear=True, owner="acceptance-highlight"
        )
        check(
            "highlight clear empties the selection",
            cleared.get("status") == "cleared"
            and data_of("get_selection").get("count") == 0,
            f"cleared={cleared.get('status')}",
        )

        # 4. Close and reopen: references survive a new document session.
        data_of("close_document", save=False)
        data_of("open_document", path=str(scratch))
        reopened = data_of("resolve_entity_reference", ref=face_entry["ref"])
        check(
            "face reference survives save/reopen",
            reopened.get("kind") == "face"
            and reopened.get("details", {}).get("area_mm2") == resolved_face["details"]["area_mm2"],
            json.dumps(reopened.get("details"))[:200],
        )

        # 5. Topology change: a disjoint second body.
        data_of("create_sketch", plane="front")
        data_of("sketch_rectangle", x1_mm=60, y1_mm=-10, x2_mm=80, y2_mm=10)
        data_of("exit_sketch")
        data_of("boss_extrude", depth_mm=10, name="SideBoss", merge=False)
        rebuilt = data_of("resolve_entity_reference", ref=face_entry["ref"])
        check(
            "face reference survives a topology-changing rebuild",
            rebuilt.get("kind") == "face" and rebuilt.get("index") is not None,
            json.dumps({k: rebuilt.get(k) for k in ("kind", "index")}),
        )

        # 6. A deleted entity fails explicitly.
        side_faces = inspect.list_faces()
        side_top = next(
            (
                face
                for face in side_faces
                if face.get("normal") == [0.0, 0.0, 1.0] and face.get("area_mm2") == 400.0
            ),
            None,
        )
        if side_top is None:
            check("side-boss top face found for the deletion test", False, "area 400 face missing")
        else:
            select_topology(face_index=side_top["index"])
            side_entry = data_of("get_selection")["entities"][0]
            data_of("delete_feature", name="SideBoss")
            check(
                "deleted entity resolves as REFERENCE_NOT_FOUND",
                error_code("resolve_entity_reference", ref=side_entry["ref"])
                == "REFERENCE_NOT_FOUND",
                f"code={error_code('resolve_entity_reference', ref=side_entry['ref'])}",
            )

        # 7. A reference from another document fails explicitly.
        data_of("new_document", kind="part")
        mismatch = error_code("resolve_entity_reference", ref=face_entry["ref"])
        check(
            "foreign-document reference fails as REFERENCE_DOCUMENT_MISMATCH",
            mismatch == "REFERENCE_DOCUMENT_MISMATCH",
            f"code={mismatch}",
        )
        data_of("close_document", save=False)

        # 8. A modified referenced face still resolves and reports new geometry.
        before_cut = data_of("resolve_entity_reference", ref=face_entry["ref"])
        data_of("create_sketch", face_index=before_cut["index"])
        data_of("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
        data_of("exit_sketch")
        data_of("cut_extrude", end_condition="through_all", name="TopCut")
        modified = data_of("resolve_entity_reference", ref=face_entry["ref"])
        check(
            "modified face resolves with its new geometry",
            modified.get("kind") == "face"
            and float(modified.get("details", {}).get("area_mm2", 0)) < 6000.0,
            json.dumps(modified.get("details"))[:200],
        )
    except Exception as error:  # noqa: BLE001 - acceptance reports and exits
        check("acceptance completed without exception", False, f"{type(error).__name__}: {error}")
    finally:
        try:
            data_of("close_document", save=False)
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
