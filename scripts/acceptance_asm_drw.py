#!/usr/bin/env python
"""Live acceptance for assemblies and drawings."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "acceptance_asm"
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


async def build_part(client: Client, path: str, width: float, height: float,
                     depth: float) -> None:
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=width, y2_mm=height
    )
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=depth, name="Body")
    assert result["ok"], result
    saved = await client.call("save_document", path=path)
    assert saved["ok"], saved
    await client.call("close_document", save=False)


async def test_assembly(client: Client) -> None:
    part_a = str(OUTPUT / "block_a.sldprt")
    part_b = str(OUTPUT / "block_b.sldprt")
    await build_part(client, part_a, 50, 30, 10)
    await build_part(client, part_b, 40, 20, 10)

    result = await client.call("new_document", kind="assembly")
    check("new assembly", result["ok"], "")

    result = await client.call("insert_component", path=part_a, fixed=True)
    check("insert fixed component", result["ok"], json.dumps(result.get("data", {}).get("component", {}).get("name")))
    result = await client.call(
        "insert_component", path=part_b, x_mm=100, y_mm=0, z_mm=0
    )
    check("insert movable component", result["ok"], "")

    listing = await client.call("list_components")
    components = listing.get("data", {}).get("components", [])
    check("two components", len(components) == 2, f"{len(components)}")
    if len(components) == 2:
        movable = [c for c in components if not c["fixed"]]
        check(
            "component placed at x=100",
            movable and abs(movable[0]["position_mm"][0] - 100) < 0.01,
            str(movable[0].get("position_mm") if movable else None),
        )

    components = listing["data"]["components"]
    fixed_component = next(c["name"] for c in components if c["fixed"])
    movable_component = next(c["name"] for c in components if not c["fixed"])

    await client.call(
        "set_component_transform", name=movable_component, x_mm=25, y_mm=0, z_mm=0
    )
    interference = await client.call("check_interference")
    check(
        "interference detected when overlapping",
        interference["ok"] and interference["data"]["count"] >= 1,
        json.dumps(interference.get("data")),
    )

    await client.call(
        "set_component_transform", name=movable_component, x_mm=100, y_mm=0, z_mm=0
    )
    interference = await client.call("check_interference")
    check(
        "no interference when separated",
        interference["ok"] and interference["data"]["count"] == 0,
        json.dumps(interference.get("data")),
    )

    result = await client.call(
        "add_mate",
        mate_type="coincident",
        component_a=fixed_component,
        direction_a="+x",
        component_b=movable_component,
        direction_b="-x",
        align="closest",
    )
    check("coincident mate", result["ok"], "")

    listing = await client.call("list_components")
    moved = next(
        (c for c in listing["data"]["components"] if c["name"] == movable_component),
        None,
    )
    check(
        "mate solved to x=50",
        moved is not None and abs(moved["position_mm"][0] - 50) < 0.01,
        str(moved.get("position_mm") if moved else None),
    )

    interference = await client.call("check_interference")
    check(
        "no interference when touching",
        interference["ok"] and interference["data"]["count"] == 0,
        json.dumps(interference.get("data")),
    )

    bbox = await client.call("get_assembly_bounding_box")
    size_x = bbox.get("data", {}).get("size_mm", [0])[0]
    check("assembly bounding box", bbox["ok"] and abs(size_x - 90) < 0.5,
          f"size_x={size_x}")

    saved = await client.call(
        "save_document", path=str(OUTPUT / "asm1.sldasm")
    )
    check("save assembly", saved["ok"], "")
    await client.call("close_document", save=False)


async def test_drawing(client: Client) -> None:
    part_a = str(OUTPUT / "block_a.sldprt")
    opened = await client.call("open_document", path=part_a)
    check("open part for drawing", opened["ok"], "")
    result = await client.call("new_drawing", model=part_a)
    check("new drawing", result["ok"], "")
    result = await client.call("drawing_insert_standard_views", model=part_a)
    check("insert standard views", result["ok"], json.dumps(result.get("data")))
    views = await client.call("list_drawing_views")
    count = views.get("data", {}).get("count", 0)
    check("drawing has views", views["ok"] and count >= 3, f"{count} views")
    exported = await client.call(
        "export_document", path=str(OUTPUT / "drawing.pdf")
    )
    check("export drawing pdf", exported["ok"], "")
    await client.call("close_document", save=False)


async def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    env.setdefault("SW_MCP_OUTPUT_ROOT", str(OUTPUT))
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
            await test_assembly(client)
            await test_drawing(client)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
