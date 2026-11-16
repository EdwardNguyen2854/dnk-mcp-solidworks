"""Live Datum selection acceptance on a newly-created disposable part only.

Uses this checkout explicitly, not a possibly unrelated editable installation.
Never saves or closes an engineer's document. Requires SOLIDWORKS already running.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solidworks_mcp.com import binding
from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.domain import inspect, session
from solidworks_mcp.tools import core, extended

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'} {name} {detail}")
    if not condition:
        raise AssertionError(name)


def call(tool, **args):
    handler = getattr(core, tool, None) or getattr(extended, tool)
    result = handler(args)
    if not result.get("ok"):
        raise RuntimeError(f"{tool}: {result}")
    return result.get("data", {})


def distance(a, b):
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5


def selection_marks():
    _, doc, _ = session.active_doc("part")
    manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
    return [int(manager.GetSelectedObjectMark(i))
            for i in range(1, int(manager.GetSelectedObjectCount2(-1)) + 1)]


def select(index, mark=0):
    def job():
        _, doc, _ = session.active_doc("part")
        inspect.select_faces(doc, [index], mark=mark)
    run(job)


def select_edge(index, mark=0):
    def job():
        _, doc, _ = session.active_doc("part")
        inspect.select_edges(doc, [index], mark=mark)
    run(job)


def main():
    title = None
    try:
        call("new_document", kind="part")
        title = run(lambda: session.doc_info(session.active_doc("part")[1])["title"])
        call("create_sketch", plane="front")
        call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
        call("exit_sketch")
        call("boss_extrude", depth_mm=25, name="DatumDisposableBase")
        volume = call("get_mass_properties")["volume_mm3"]
        check("fixture volume", abs(volume - 150000) < 1, str(volume))
        select(0)
        reference = call("get_selection")["entities"][0]["ref"]
        check("identity revalidation", call("resolve_entity_reference", ref=reference)["index"] == 0)
        select(1, 7)
        baseline = call("get_selection")
        before_features = call("list_features")
        dirty = run(lambda: session.doc_info(session.active_doc("part")[1])["dirty"])
        owner = "datum-live-" + uuid4().hex
        applied = call("highlight_entities", refs=[reference], owner=owner)
        check("owned highlight applies", applied["status"] == "applied" and applied["owned"] == 1)
        marks = run(selection_marks)
        check("engineer mark preserved during highlight", len(marks) == 2 and marks[0] == 7 and marks[1] >= 65536, str(marks))
        cleared = call("highlight_entities", refs=[], owner=owner, clear=True)
        check("owned cleanup acknowledged", cleared["status"] == "cleared")
        check("engineer selection preserved after cleanup", call("get_selection")["entities"] == baseline["entities"] and run(selection_marks) == [7])
        check("highlight creates no feature", call("list_features") == before_features)
        check("highlight preserves dirty baseline", run(lambda: session.doc_info(session.active_doc("part")[1])["dirty"]) == dirty)
        check("highlight preserves solid geometry", abs(call("get_mass_properties")["volume_mm3"] - volume) < 1)
        fenced = call("highlight_entities", refs=[reference], owner=owner)
        check("late apply is fenced", fenced["status"] == "cleared" and run(selection_marks) == [7])
        plane = "DatumSelectedFaceOffset"
        call("create_reference_plane", entity_ref=reference, distance_mm=5, name=plane)
        check("selected-face positive offset commits", plane in call("list_reference_planes")["planes"])
        negative = "DatumSelectedFaceNegativeOffset"
        call("create_reference_plane", entity_ref=reference, distance_mm=-5, name=negative)
        check("selected-face negative offset commits", negative in call("list_reference_planes")["planes"])
        check("reference-plane operations preserve solid volume", abs(call("get_mass_properties")["volume_mm3"] - volume) < 1)

        # --- edge references. A box edge still has a vertex pair, so it must be
        # trimmed-vertex sourced; a hole's circular edge has no usable vertex
        # pair, so its span must come from the curve's trim range instead —
        # never from untrimmed 0.0/1.0 samples, which describe the support curve.
        lines = run(lambda: inspect.list_edges(curve_type="line"))
        check("line edges enumerated", len(lines) >= 12, str(len(lines)))
        line = min(lines, key=lambda row: row["index"])
        select_edge(line["index"])
        line_resolved = call("resolve_entity_reference", ref=call("get_selection")["entities"][0]["ref"])
        line_fp = line_resolved["details"]
        check("line edge reference round-trips",
              line_resolved["kind"] == "edge" and line_resolved["index"] == line["index"],
              f"index={line_resolved['index']} expected={line['index']}")
        check("line edge endpoints are vertex-trimmed",
              line_fp.get("endpoint_source") == "trimmed_vertices", str(line_fp.get("endpoint_source")))
        span = distance(line_fp["start_mm"], line_fp["end_mm"])
        check("line edge span matches its length", abs(span - line_fp["length_mm"]) < 1e-3,
              f"span={span:.4f} length={line_fp['length_mm']}")

        faces = run(lambda: inspect.list_faces())
        planar = [f for f in faces
                  if f.get("surface") == "plane" and isinstance(f.get("area_mm2"), (int, float))]
        largest = max(planar, key=lambda f: f["area_mm2"])["index"]
        call("simple_hole", diameter_mm=10, face_index=largest, x_mm=50, y_mm=30,
             end_condition="through_all", name="DatumEdgeProbe")
        circles = run(lambda: inspect.list_edges(curve_type="circle"))
        check("hole produced circular edges", len(circles) >= 2, str(len(circles)))
        for row in circles:
            where = f"circle edge {row['index']}"
            check(f"{where} reports centre and radius",
                  abs(float(row.get("radius_mm", 0)) - 5.0) < 1e-3, str(row.get("radius_mm")))
            check(f"{where} has a bounded span",
                  row.get("start_mm") is not None and row.get("end_mm") is not None,
                  str(row.get("endpoint_source")))
            check(f"{where} is closed", row.get("closed") is True, str(row.get("closed")))
            for key in ("start_mm", "end_mm"):
                to_centre = distance(row[key], row["center_mm"])
                check(f"{where} {key} lies on the circle",
                      abs(to_centre - row["radius_mm"]) < 1e-3, f"d={to_centre:.4f}")
        circle = circles[0]
        select_edge(circle["index"])
        circle_resolved = call("resolve_entity_reference", ref=call("get_selection")["entities"][0]["ref"])
        check("circular edge reference round-trips",
              circle_resolved["kind"] == "edge" and circle_resolved["index"] == circle["index"],
              f"index={circle_resolved['index']} expected={circle['index']}")

        print(f"RESULT {sum(CHECKS)}/{len(CHECKS)} passed; SOLIDWORKS {run(lambda: binding.value(session.app().RevisionNumber))}")
    finally:
        if title is not None:
            # The unique unsaved fixture title was created by this run. Do not
            # call close_document: that would close whichever document is active.
            run(lambda: session.app().CloseDoc(title))


if __name__ == "__main__":
    worker = ComWorker(timeout=60)
    worker.start()
    set_worker(worker)
    try:
        main()
    finally:
        worker.stop()
