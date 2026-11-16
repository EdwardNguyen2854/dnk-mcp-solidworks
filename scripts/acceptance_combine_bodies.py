#!/usr/bin/env python
"""Live acceptance: `combine_bodies` through the registered MCP tool.

Proves the shipped tool (not an ad-hoc probe) performs add, subtract and common
on the canonical overlapping-prism fixture, comparing measured volume against a
hand calculation and checking body count, rebuild state and feature creation.
Also proves invalid indices are rejected before any COM mutation.

Runs the MCP server over stdio against the open SOLIDWORKS session; creates and
closes its own documents (never saves over anything). Save your work first.

Usage:
    python scripts/acceptance_combine_bodies.py
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[tuple[str, bool, str]] = []

# (x1, y1, x2, y2, depth) on the front plane, in millimetres.
PRISM_A = (0.0, 0.0, 10.0, 10.0, 10.0)
PRISM_B = (5.0, 2.0, 15.0, 12.0, 12.0)


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def parse(result) -> dict:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    return {}


def near(actual: float, expected: float, tolerance: float = 1e-4) -> bool:
    return abs(actual - expected) <= max(abs(expected) * tolerance, 0.05)


def prism_volume(prism: tuple[float, ...]) -> float:
    x1, y1, x2, y2, depth = prism
    return (x2 - x1) * (y2 - y1) * depth


def overlap_volume(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    lengths = [
        max(0.0, min(a[2], b[2]) - max(a[0], b[0])),
        max(0.0, min(a[3], b[3]) - max(a[1], b[1])),
        min(a[4], b[4]),
    ]
    return math.prod(lengths)


class Client:
    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, tool: str, **arguments) -> dict:
        envelope = parse(await self.session.call_tool(tool, arguments))
        if not envelope.get("ok"):
            print(f"      {tool}: {json.dumps(envelope.get('error'))}")
        return envelope

    async def volume(self) -> float:
        result = await self.call("get_mass_properties")
        return float(result.get("data", {}).get("volume_mm3", -1))

    async def new_part(self) -> None:
        await self.call("new_document", kind="part")

    async def close(self) -> None:
        await self.call("close_document", save=False)


async def build_two_prisms(client: Client) -> list[dict]:
    await client.new_part()
    for x1, y1, x2, y2, depth in (PRISM_A, PRISM_B):
        sketch = await client.call("create_sketch", plane="front")
        assert sketch.get("ok"), sketch
        rectangle = await client.call(
            "sketch_rectangle", x1_mm=x1, y1_mm=y1, x2_mm=x2, y2_mm=y2
        )
        assert rectangle.get("ok"), rectangle
        await client.call("exit_sketch")
        extrude = await client.call("boss_extrude", depth_mm=depth, merge=False)
        assert extrude.get("ok"), extrude
    listed = await client.call("list_bodies")
    assert listed.get("ok"), listed
    return listed["data"]["bodies"]


def body_index_by_min_corner(bodies: list[dict], prism: tuple[float, ...]) -> int | None:
    for body in bodies:
        box = body.get("box_mm") or {}
        low = box.get("min") or []
        if len(low) >= 2 and near(low[0], prism[0], 1e-3) and near(low[1], prism[1], 1e-3):
            return body["index"]
    return None


async def check_one_operation(client: Client, operation: str) -> None:
    expected = {
        "add": prism_volume(PRISM_A) + prism_volume(PRISM_B) - overlap_volume(PRISM_A, PRISM_B),
        "subtract": prism_volume(PRISM_A) - overlap_volume(PRISM_A, PRISM_B),
        "common": overlap_volume(PRISM_A, PRISM_B),
    }[operation]

    bodies = await build_two_prisms(client)
    check(f"{operation}: fixture has two bodies", len(bodies) == 2, f"{len(bodies)}")
    check(
        f"{operation}: source volumes match hand calc",
        sorted(round(math.prod(b["box_mm"]["max"][i] - b["box_mm"]["min"][i] for i in range(3)), 4) for b in bodies)
        == sorted([prism_volume(PRISM_A), prism_volume(PRISM_B)]),
        json.dumps([b.get("box_mm") for b in bodies]),
    )

    main = body_index_by_min_corner(bodies, PRISM_A)
    tool = body_index_by_min_corner(bodies, PRISM_B)
    if main is None or tool is None:
        check(f"{operation}: identified main/tool bodies", False, f"main={main} tool={tool}")
        await client.close()
        return

    result = await client.call(
        "combine_bodies",
        operation=operation,
        main_body_index=main,
        tool_body_index=tool,
    )
    data = result.get("data") or {}
    evidence = result.get("evidence") or {}
    volume = float((evidence.get("mass_properties") or {}).get("volume_mm3", -1))
    before = evidence.get("feature_tree_before") or []
    after = evidence.get("feature_tree_after") or []
    new_features = sorted(set(after) - set(before))
    wrong = (evidence.get("whats_wrong") or {}).get("count")

    check(
        f"{operation}: tool succeeded",
        bool(result.get("ok")),
        json.dumps(result.get("error")) if not result.get("ok") else "",
    )
    check(
        f"{operation}: one solid body remains",
        evidence.get("body_count") == 1,
        f"{evidence.get('body_count')}",
    )
    check(
        f"{operation}: volume matches hand calc",
        near(volume, expected),
        f"{volume:.4f} vs {expected:.4f}",
    )
    check(
        f"{operation}: clean rebuild / What's Wrong 0",
        bool(evidence.get("rebuild", {}).get("ok")) and wrong == 0,
        f"whats_wrong={wrong}",
    )
    check(
        f"{operation}: exactly one Combine feature added",
        len(new_features) == 1 and "Combine" in new_features[0],
        json.dumps(new_features),
    )
    check(
        f"{operation}: result reports the requested bodies",
        data.get("main_body_index") == main and data.get("tool_body_index") == tool,
        json.dumps(data),
    )
    await client.close()


async def check_invalid_index_is_rejected(client: Client) -> None:
    bodies = await build_two_prisms(client)
    before_volume = await client.volume()
    result = await client.call(
        "combine_bodies", operation="add", main_body_index=0, tool_body_index=0
    )
    error = result.get("error") or {}
    after = await client.call("list_bodies")
    after_volume = await client.volume()
    check(
        "invalid body indices rejected before COM",
        not result.get("ok") and error.get("code") == "INVALID_PARAMETER",
        json.dumps(error),
    )
    check(
        "invalid request left the model unchanged",
        after.get("data", {}).get("count") == len(bodies)
        and near(after_volume, before_volume),
        f"bodies {after.get('data', {}).get('count')} volume {after_volume:.4f}",
    )
    await client.close()


async def main() -> int:
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    env.setdefault("SW_MCP_OUTPUT_ROOT", str(ROOT / "artifacts" / "acceptance"))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "solidworks_mcp"],
        env=env,
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = Client(session)
            for operation in ("subtract", "add", "common"):
                await check_one_operation(client, operation)
            await check_invalid_index_is_rejected(client)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} combine-body checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
