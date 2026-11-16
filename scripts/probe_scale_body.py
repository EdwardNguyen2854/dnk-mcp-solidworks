#!/usr/bin/env python
"""Live probe of IFeatureManager.InsertScale on one scratch rectangular prism."""
from __future__ import annotations

import json

from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.domain import documents, features, inspect, session, sketch


def probe() -> dict:
    opened = False
    try:
        documents.new_document("part")
        opened = True
        sketch.create_sketch("front")
        sketch.rectangle(0.0, 0.0, 10.0, 20.0)
        sketch.exit_sketch()
        features.boss_extrude(depth_mm=30.0, merge=False)
        _, doc, _ = session.active_doc(("part",))
        before = {
            "bodies": inspect.list_bodies(doc),
            "mass": inspect.mass_properties(doc),
            "bounds": inspect.bounding_box(doc),
        }
        inspect.select_bodies(doc, [0])
        feature = doc.FeatureManager.InsertScale(1, True, 2.0, 2.0, 2.0)
        rebuild = inspect.rebuild(doc)
        after = {
            "bodies": inspect.list_bodies(doc),
            "mass": inspect.mass_properties(doc),
            "bounds": inspect.bounding_box(doc),
            "whats_wrong": inspect.whats_wrong(doc),
        }
        return {"feature_returned": feature is not None, "before": before,
                "rebuild": rebuild, "after": after,
                "expected_volume_mm3": 10.0 * 20.0 * 30.0 * 8.0}
    finally:
        if opened:
            documents.close_document(save=False)


if __name__ == "__main__":
    worker = ComWorker()
    set_worker(worker)
    worker.start()
    try:
        print(json.dumps(run(probe), indent=2, default=str))
    finally:
        worker.stop()
