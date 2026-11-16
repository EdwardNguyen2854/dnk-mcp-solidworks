#!/usr/bin/env python
"""Live regressions for geometry diagnostics and counterbore rollback.

Uses scratch documents only. Save user work before running. Fault injection
is local to this test process and executes on the STA; it is not an MCP tool.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import acceptance as geometry
import acceptance_modelling_depth as depth
from solidworks_mcp.com.worker import ComWorker
from solidworks_mcp.domain import documents, features, inspect, session, sketch
from solidworks_mcp.errors import FeatureBuildError, InvalidParameterError

ROOT = Path(__file__).resolve().parents[1]


def counterbore_rollback() -> dict:
    """Build the real pilot, reject the second cut, and measure restoration."""
    documents.new_document("part")
    _, doc, _ = session.active_doc(("part",))
    original_hole = features._simple_hole_feature
    try:
        sketch.create_sketch("front")
        sketch.rectangle(0, 0, 40, 40)
        sketch.exit_sketch()
        features.boss_extrude(depth_mm=20, name="RollbackBody")
        face = next(item for item in inspect.list_faces(doc)
                    if (item.get("normal") or [0, 0, 0])[2] > 0.99)
        before = features._model_fingerprint(doc)
        calls = 0

        def fail_second_cut(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise FeatureBuildError("injected second-cut failure")
            return original_hole(*args, **kwargs)

        features._simple_hole_feature = fail_second_cut
        failure = None
        try:
            features.counterbore_hole(6, 10, 4, face["index"], 20, 20,
                                     depth_mm=15)
        except FeatureBuildError as exc:
            failure = str(exc)
        after = features._model_fingerprint(doc)
        return {"passed": calls == 2 and failure is not None
                and features._same_fingerprint(before, after),
                "calls": calls, "failure": failure,
                "restored_volume_mm3": after["mass"]["volume_mm3"]}
    finally:
        features._simple_hole_feature = original_hole
        documents.close_document(save=False)


def geometry_comparison() -> dict:
    owned = []
    try:
        for height in (20, 21):
            created = documents.new_document("part")["document"]
            owned.append(created["title"])
            sketch.create_sketch("front")
            sketch.rectangle(0, 0, 40, 40)
            sketch.exit_sketch()
            features.boss_extrude(depth_mm=height, name="ComparisonBody")
        result = inspect.compare_model_geometry(owned[0], 0.01, 0.01, 0.01)
        data = result["data"]
        looser = inspect.compare_model_geometry(owned[0], 1601, 1.01, 1.01)["data"]
        self_rejected = False
        try:
            inspect.compare_model_geometry(owned[1], 1, 1, 1)
        except InvalidParameterError:
            self_rejected = True
        return {"passed": data["passed"] is False and looser["passed"] is True
                and self_rejected
                and abs(data["deltas"]["volume_mm3"] - 1600) < 0.01
                and abs(data["deltas"]["max_extrema_mm"] - 1) < 0.001,
                "strict": data, "self_comparison_rejected": self_rejected}
    finally:
        for title in reversed(owned):
            session.app().CloseDoc(title)


async def main() -> int:
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    env.setdefault("SW_MCP_OUTPUT_ROOT", str(ROOT / "artifacts" / "reliability"))
    params = StdioServerParameters(command=sys.executable,
                                  args=["-m", "solidworks_mcp"], env=env,
                                  cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as connected:
            await connected.initialize()
            client = geometry.Client(connected)
            before = await client.call("list_documents")
            await geometry.test_box(client)
            await depth.test_hole_recipes(client)
            await depth.test_tapped_and_cosmetic_thread(client)
            after = await client.call("list_documents")
            geometry.check("initial documents preserved by geometry regressions",
                           before.get("data") == after.get("data"))
    worker = ComWorker()
    worker.start()
    try:
        rollback = worker.call(counterbore_rollback)
        geometry.check("real counterbore pilot rolls back after second-cut failure",
                       rollback["passed"], json.dumps(rollback))
        compared = worker.call(geometry_comparison)
        geometry.check("model comparison respects explicit limits and rejects self",
                       compared["passed"], json.dumps(compared))
    finally:
        worker.stop()
    checks = geometry.CHECKS + depth.CHECKS
    passed = sum(bool(ok) for _, ok, _ in checks)
    print(f"\n{passed}/{len(checks)} reliability checks passed", flush=True)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
