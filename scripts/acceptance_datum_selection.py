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
from solidworks_mcp.tools import core

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'} {name} {detail}")
    if not condition:
        raise AssertionError(name)


def call(tool, **args):
    result = getattr(core, tool)(args)
    if not result.get("ok"):
        raise RuntimeError(f"{tool}: {result}")
    return result.get("data", {})


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
