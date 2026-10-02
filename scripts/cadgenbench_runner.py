#!/usr/bin/env python
"""Run explicit CADGenBench generation cases through the local MCP server.

This runner deliberately consumes a prepared tool-call manifest; it does not
download benchmark data, generate tool calls, or submit results to the Space.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_TOOLS = {"new_document", "open_document", "save_document", "close_document", "export_document", "verify_export"}
CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def parse_envelope(result: Any) -> dict[str, Any]:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            try:
                value = json.loads(item.text)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                return value
    return {"ok": False, "error": {"message": "MCP tool returned no JSON envelope"}}


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest must contain a non-empty 'cases' array")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("each case must have a string id")
        case_id = case["id"]
        if not CASE_ID.fullmatch(case_id) or case_id in seen:
            raise ValueError(f"invalid or duplicate case id: {case_id!r}")
        seen.add(case_id)
        calls = case.get("calls")
        if not isinstance(calls, list):
            raise ValueError(f"case {case_id!r} must have a calls array")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("tool"), str):
                raise ValueError(f"case {case_id!r} has an invalid call")
            if call["tool"] in CONTROLLED_TOOLS:
                raise ValueError(f"{call['tool']} is managed by the runner")
            if not isinstance(call.get("args", {}), dict):
                raise ValueError(f"arguments for {call['tool']} must be an object")
    return cases


async def run_case(
    session: ClientSession,
    case: dict[str, Any],
    output_root: Path,
    exposed: set[str],
) -> dict[str, Any]:
    case_id = case["id"]
    output_rel = f"{case_id}/output.step"
    record: dict[str, Any] = {"id": case_id, "ok": False, "calls": []}
    document_open = False
    try:
        started = parse_envelope(await session.call_tool("new_document", {"kind": "part"}))
        record["calls"].append({"tool": "new_document", "result": started})
        if not started.get("ok"):
            return record
        document_open = True

        for call in case["calls"]:
            name = call["tool"]
            if name not in exposed:
                result = {"ok": False, "error": {"message": f"Tool is not exposed: {name}"}}
            else:
                result = parse_envelope(await session.call_tool(name, call.get("args", {})))
            record["calls"].append({"tool": name, "result": result})
            if not result.get("ok"):
                return record

        exported = parse_envelope(await session.call_tool("export_document", {"path": output_rel, "file_format": "step"}))
        record["calls"].append({"tool": "export_document", "result": exported})
        if not exported.get("ok"):
            return record

        verified = parse_envelope(await session.call_tool("verify_export", {"path": str(output_root / output_rel)}))
        record["calls"].append({"tool": "verify_export", "result": verified})
        record["ok"] = bool(verified.get("ok"))
        record["output_step"] = output_rel
        return record
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    finally:
        if document_open:
            try:
                await session.call_tool("close_document", {"save": False})
            except Exception as exc:
                record["cleanup_error"] = f"{type(exc).__name__}: {exc}"


async def run(manifest: Path, output_root: Path) -> int:
    cases = load_cases(manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["SW_MCP_OUTPUT_ROOT"] = str(output_root.resolve())
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    params = StdioServerParameters(command=sys.executable, args=["-m", "solidworks_mcp"], env=env, cwd=str(ROOT))
    results: list[dict[str, Any]] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            exposed = {tool.name for tool in (await session.list_tools()).tools}
            required = {"new_document", "close_document", "export_document", "verify_export"}
            if not required <= exposed:
                raise RuntimeError(f"Required MCP tools unavailable: {sorted(required - exposed)}")
            for case in cases:
                result = await run_case(session, case, output_root.resolve(), exposed)
                results.append(result)
                print(f"{'PASS' if result['ok'] else 'FAIL'} {case['id']}")

    summary = {"benchmark": "CADGenBench", "mode": "local-mcp-generation", "results": results,
               "passed": sum(bool(r.get("ok")) for r in results), "total": len(results)}
    (output_root / "run-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"CADGenBench local run: {summary['passed']}/{summary['total']} exported and verified")
    return 0 if summary["passed"] == summary["total"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON manifest containing prepared MCP tool-call sequences")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "cadgenbench",
                        help="MCP output sandbox and local result directory")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.manifest.resolve(), args.output_root.resolve()))
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
