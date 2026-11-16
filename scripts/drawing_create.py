#!/usr/bin/env python
"""Create and save a 2D drawing from the active part."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get(
    "SW_MCP_OUTPUT_ROOT",
    str(Path.home() / "Documents" / "dnk-mcp-solidworks"),
))


def parse(result) -> dict:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    return {}


async def call(session: ClientSession, name: str, args: dict | None = None) -> dict:
    env = parse(await session.call_tool(name, args or {}))
    status = "ok" if env.get("ok") else "FAIL"
    print(f"{status:4} {name:36} {json.dumps(env)[:240]}")
    return env


async def main() -> int:
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
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

            active = await call(session, "get_active_document_info")
            document = (active.get("data") or {}).get("document") or {}
            model_reference = document.get("path") or document.get("title")
            configuration = document.get("active_configuration")
            if not model_reference or not configuration:
                raise RuntimeError(
                    "an active part/assembly with a readable configuration is required"
                )

            for name, args in [
                ("new_drawing", {}),
                ("drawing_insert_view",
                 {"view": "isometric", "x_mm": 240, "y_mm": 200,
                  "model_reference": model_reference,
                  "configuration": configuration}),
                ("drawing_insert_standard_views",
                 {"model_reference": model_reference,
                  "configuration": configuration}),
                ("drawing_auto_dimension", {"view": "Drawing View1"}),
                ("capture_screenshot", {"path": str(OUT / "drawing.png")}),
                ("export_document", {"path": str(OUT / "drawing.pdf")}),
                ("save_document", {"path": str(OUT / "active-drawing.SLDDRW")}),
            ]:
                envelope = await call(session, name, args)
                if not envelope.get("ok"):
                    failures += 1
    print("CREATE:", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
