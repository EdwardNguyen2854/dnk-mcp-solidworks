#!/usr/bin/env python
"""Live acceptance suite: drive the MCP server over stdio and verify measured
geometry against hand calculations.

Usage:
    python scripts/acceptance.py [--keep]
"""
from __future__ import annotations

import argparse
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


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def parse(result) -> dict:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    return {}


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


async def test_box(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60
    )
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=25, name="Base")
    volume = await client.volume()
    check("box extrude volume", abs(volume - 150000) < 1, f"{volume:.2f} mm3")
    check("box extrude evidence", "evidence" in result, "evidence present")

    edges = await client.call("list_edges")
    verticals = [
        edge["index"]
        for edge in edges["data"]["edges"]
        if abs(edge.get("length_mm", 0) - 25) < 0.01
    ]
    check("list_edges finds verticals", len(verticals) == 4, str(verticals))

    result = await client.call("fillet", radius_mm=5, edge_indices=verticals)
    expected = 150000 - 4 * (25 - math.pi * 25 / 4) * 25
    volume = await client.volume()
    check(
        "fillet 4 verticals",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )

    result = await client.call("set_material", name="6061 Alloy")
    density = result.get("data", {}).get("density_kg_m3", 0)
    check("set_material 6061", abs(density - 2700) < 50, f"{density} kg/m3")
    await client.close()


async def test_shell(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Box")

    faces = await client.call("list_faces")
    top = None
    for face in faces["data"]["faces"]:
        normal = face.get("normal")
        box = face.get("box_mm", {})
        if normal and abs(normal[2] - 1) < 1e-6 and box.get("max", [0, 0, 0])[2] > 24.9:
            top = face["index"]
            break
    check("find top face", top is not None, f"index {top}")

    result = await client.call("shell", thickness_mm=2, face_indices=[top])
    expected = 100 * 60 * 25 - (100 - 4) * (60 - 4) * (25 - 2)
    volume = await client.volume()
    check(
        "shell top face",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_through_cut(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Box")

    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=50, center_y_mm=30, radius_mm=10)
    await client.call("exit_sketch")
    result = await client.call(
        "cut_extrude", end_condition="through_all_both", name="ThroughHole"
    )
    expected = 150000 - math.pi * 100 * 25
    volume = await client.volume()
    check(
        "through_all_both cut",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_revolve(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_line", x1_mm=0, y1_mm=0, x2_mm=0, y2_mm=10, construction=True
    )
    await client.call("sketch_rectangle", x1_mm=20, y1_mm=0, x2_mm=30, y2_mm=10)
    await client.call("exit_sketch")
    result = await client.call("revolve", angle_deg=360, name="Ring")
    expected = math.pi * (30**2 - 20**2) * 10
    volume = await client.volume()
    check(
        "revolve ring volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_dimension(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=50, y2_mm=30)
    listing = await client.call("list_sketch_segments")
    target = None
    for segment in listing["data"]["segments"]:
        if segment.get("type") == "line" and abs(segment.get("length_mm", 0) - 50) < 0.01:
            target = segment["index"]
            break
    check("sketch segment listing", target is not None, f"segment {target}")
    result = await client.call(
        "sketch_add_dimension",
        segment_indices=[target],
        value_mm=80,
        placement_mm=[25, -10],
    )
    listing = await client.call("list_sketch_segments")
    lengths = [
        segment.get("length_mm", 0)
        for segment in listing["data"]["segments"]
        if segment.get("type") == "line"
    ]
    check(
        "driving dimension applied",
        result.get("data", {}).get("value_applied") and max(lengths) > 79,
        f"lengths={lengths}",
    )
    await client.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
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
            await test_box(client)
            await test_shell(client)
            await test_through_cut(client)
            await test_revolve(client)
            await test_dimension(client)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
