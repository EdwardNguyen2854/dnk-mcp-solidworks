"""Fixed disposable-part actions for Datum's live acceptance runner.

Creates only a new file under the approved OpenCode temporary directory; every
later action checks that exact path. No engineer document is modified or closed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["create", "select", "read", "edit", "close"])
parser.add_argument("path", type=Path)
args = parser.parse_args()
path = args.path.resolve()
root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
if not path.is_relative_to(root.resolve()) or path.name != "DatumAcceptance.SLDPRT":
    parser.error("fixture must be DatumAcceptance.SLDPRT under the approved OpenCode temp directory")
os.environ["SW_MCP_OUTPUT_ROOT"] = str(path.parent)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solidworks_mcp.com import binding
from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.domain import inspect, session
from solidworks_mcp.tools import core


def call(tool, **params):
    result = getattr(core, tool)(params)
    if not result.get("ok"):
        raise RuntimeError(f"{tool}: {result}")
    return result.get("data", {})


def require_fixture():
    _, doc, _ = session.active_doc("part")
    if Path(session.doc_info(doc)["path"]).resolve() != path:
        raise RuntimeError("active document is not this run's disposable fixture; refusing action")
    return doc


def snapshot():
    doc = require_fixture()
    manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
    return {"document": session.doc_info(doc), "features": session.list_feature_infos(doc),
            "planes": session.plane_names(doc), "volume": inspect.mass_properties(doc)["volume_mm3"],
            "selection_marks": [int(manager.GetSelectedObjectMark(i)) for i in range(1, int(manager.GetSelectedObjectCount2(-1)) + 1)]}


def main():
    if args.action == "create":
        if path.exists():
            raise RuntimeError("fixture path already exists; refusing overwrite")
        call("new_document", kind="part")
        call("create_sketch", plane="front")
        call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
        call("exit_sketch")
        call("boss_extrude", depth_mm=25, name="DatumAcceptanceBase")
        call("save_document", path=str(path))
    else:
        run(require_fixture)
    if args.action == "select":
        def select_top():
            doc = require_fixture()
            faces = inspect.list_faces()
            top = next(face for face in faces if face.get("normal", [0, 0, 0])[2] > 0.999 and face["box_mm"]["max"][2] > 24.9)
            inspect.select_faces(doc, [top["index"]], mark=0)
        run(select_top)
    elif args.action == "edit":
        call("create_sketch", plane="front")
        call("sketch_rectangle", x1_mm=10, y1_mm=10, x2_mm=20, y2_mm=20)
        call("exit_sketch")
        call("cut_extrude", end_condition="through_all_both", name="DatumAcceptanceEdit")
    elif args.action == "close":
        run(lambda: session.app().CloseDoc(str(path)))
        return {"closed_fixture": str(path)}
    return run(snapshot)


worker = ComWorker(timeout=60)
worker.start()
set_worker(worker)
try:
    print(json.dumps(main()))
finally:
    worker.stop()
