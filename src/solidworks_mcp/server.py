"""MCP stdio server: tier-filtered tool listing and dispatch.

Handlers are synchronous and reach SOLIDWORKS through the dedicated STA COM
worker, so the asyncio loop never touches COM directly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__, capabilities as capabilities_module, registry
from .com.worker import ComWorker, set_worker
from .config import VALID_TIERS, get_config, load_config, setup_logging
from .errors import SwMcpError, fail, translate_com_error

log = logging.getLogger(__name__)

server = Server("dnk-mcp-solidworks")


def _import_tools() -> None:
    from .tools import advanced, core, debug, extended  # noqa: F401


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    config = get_config()
    return [
        types.Tool(
            name=spec.name,
            description=spec.description,
            inputSchema=spec.input_schema,
        )
        for spec in registry.visible_tools(config.tool_tier)
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.ContentBlock]:
    try:
        envelope = await asyncio.to_thread(registry.invoke, name, arguments)
    except SwMcpError as error:
        envelope = fail(error)
    except Exception as error:  # noqa: BLE001 - never leak raw COM errors
        log.exception("tool %s crashed", name)
        envelope = fail(translate_com_error(error, f"tool {name}"))
    images = envelope.pop("_images", None) or []
    content: list[types.ContentBlock] = [
        types.TextContent(
            type="text",
            text=json.dumps(envelope, indent=1, ensure_ascii=False, default=str),
        )
    ]
    for image in images:
        content.append(
            types.ImageContent(
                type="image", data=image["data"], mimeType=image["mime"]
            )
        )
    return content


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dnk-mcp-solidworks")
    parser.add_argument("--tier", choices=VALID_TIERS, help="tool tier override")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport; streamable-http is loopback-only and intended for ToolHive",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="loopback host for streamable-http (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="port for streamable-http (default: 8765)",
    )
    parser.add_argument(
        "--http-path",
        default="/mcp",
        help="endpoint path for streamable-http (default: /mcp)",
    )
    parser.add_argument(
        "--list-tools", action="store_true", help="print the tool catalog and exit"
    )
    parser.add_argument(
        "--check", action="store_true", help="print live capabilities and exit"
    )
    parser.add_argument(
        "--install-skill",
        metavar="DIR",
        help="copy the bundled workflow skills into DIR and exit",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.transport == "streamable-http":
        from .http_transport import is_loopback_host

        if not is_loopback_host(args.host):
            parser.error("--host must be localhost or a loopback IP for streamable-http")
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        if (
            not args.http_path.startswith("/")
            or "?" in args.http_path
            or "#" in args.http_path
        ):
            parser.error("--http-path must be an absolute path without query or fragment")

    config = load_config(tool_tier=args.tier)
    setup_logging(config)
    _import_tools()

    if args.list_tools:
        for spec in registry.visible_tools(config.tool_tier):
            print(f"{spec.tier:9} {spec.name:28} {spec.description.splitlines()[0]}")
        return 0

    if args.install_skill:
        from .skills import install_skills

        installed = install_skills(args.install_skill)
        for path in installed:
            print(path)
        return 0

    worker = ComWorker(timeout=config.operation_timeout_sec)
    worker.start()
    set_worker(worker)
    try:
        if args.check:
            print(
                json.dumps(
                    capabilities_module.collect(),
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )
            return 0
        log.info(
            "dnk-mcp-solidworks %s starting (tier=%s)", __version__, config.tool_tier
        )
        if args.transport == "streamable-http":
            from .http_transport import serve_streamable_http

            asyncio.run(
                serve_streamable_http(
                    server,
                    host=args.host,
                    port=args.port,
                    path=args.http_path,
                )
            )
        else:
            asyncio.run(_serve())
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
