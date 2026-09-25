#!/usr/bin/env python
"""M1 acceptance: drive the server over stdio and verify the closed loop."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def parse(result) -> dict:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    return {}


async def call(session: ClientSession, name: str, args: dict | None = None) -> dict:
    envelope = parse(await session.call_tool(name, args or {}))
    status = "ok" if envelope.get("ok") else "FAIL"
    print(f"{status:4} {name} {json.dumps(envelope)[:160]}")
    return envelope


async def main() -> int:
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    env.setdefault("SW_MCP_OUTPUT_ROOT", str(ROOT / "artifacts" / "smoke"))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "solidworks_mcp"],
        env=env,
        cwd=str(ROOT),
    )
    failures = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            print(f"tools exposed: {len(names)}")
            assert "boss_extrude" in names, names

            if not (await call(session, "get_status"))["ok"]:
                failures += 1

            for name, args in [
                ("new_document", {"kind": "part"}),
                ("create_sketch", {"plane": "front"}),
                ("sketch_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 50, "y2_mm": 30}),
                ("exit_sketch", {}),
                ("boss_extrude", {"depth_mm": 20, "name": "SmokePad"}),
                ("list_features", {}),
                ("get_mass_properties", {}),
                ("get_bounding_box", {}),
                ("check_errors", {}),
                ("capture_screenshot", {"path": "smoke/part.png"}),
                ("export_document", {"path": "smoke/part.stl"}),
            ]:
                envelope = await call(session, name, args)
                if not envelope.get("ok"):
                    failures += 1
                if name == "get_mass_properties":
                    volume = envelope.get("data", {}).get("volume_mm3")
                    expected = 50 * 30 * 20
                    if volume is None or abs(volume - expected) > 0.01:
                        print(f"FAIL volume {volume} != {expected}")
                        failures += 1
                    else:
                        print(f"     volume {volume} mm3 matches hand calc")

            await call(session, "close_document", {"save": False})
    print("SMOKE:", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
