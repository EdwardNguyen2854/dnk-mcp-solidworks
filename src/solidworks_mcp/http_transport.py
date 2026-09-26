"""Loopback Streamable HTTP transport used by ToolHive.

The normal server remains stdio-only. This module is an explicit opt-in
adapter for local ToolHive deployments: SOLIDWORKS and the COM worker stay in
the host Python process, while ToolHive connects to a loopback HTTP endpoint.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from ipaddress import ip_address
from typing import Any


def is_loopback_host(host: str) -> bool:
    """Return whether *host* names only the local machine."""
    candidate = host.strip().lower()
    if candidate == "localhost":
        return True
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return ip_address(candidate).is_loopback
    except ValueError:
        return False


def _validate_path(path: str) -> str:
    if not path.startswith("/") or "?" in path or "#" in path:
        raise ValueError(
            "the HTTP MCP path must be an absolute path without query or fragment"
        )
    return path


def _transport_security_settings() -> Any:
    from mcp.server.transport_security import TransportSecuritySettings

    # The endpoint is loopback-only, but keep the SDK's DNS-rebinding checks
    # enabled as an additional guard for local clients and ToolHive proxies.
    names = ("localhost", "127.0.0.1", "[::1]")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[name for host in names for name in (host, f"{host}:*")],
        allowed_origins=[
            origin
            for host in names
            for origin in (f"http://{host}", f"http://{host}:*")
        ],
    )


class _StreamableHTTPASGIApp:
    """Small ASGI adapter kept local to avoid depending on FastMCP internals."""

    def __init__(self, session_manager: Any) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def build_streamable_http_app(mcp_server: Any, *, path: str = "/mcp") -> Any:
    """Build a Starlette app serving *mcp_server* over Streamable HTTP."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Route

    path = _validate_path(path)
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        security_settings=_transport_security_settings(),
    )
    transport_app = _StreamableHTTPASGIApp(session_manager)

    @asynccontextmanager
    async def lifespan(_: Starlette):
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Route(path, endpoint=transport_app)],
        lifespan=lifespan,
    )


async def serve_streamable_http(
    mcp_server: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    path: str = "/mcp",
) -> None:
    """Serve *mcp_server* on a loopback-only Streamable HTTP endpoint."""
    if not is_loopback_host(host):
        raise ValueError("Streamable HTTP is restricted to localhost/loopback hosts")
    if not 1 <= port <= 65535:
        raise ValueError("HTTP port must be between 1 and 65535")

    import uvicorn

    app = build_streamable_http_app(mcp_server, path=path)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    await uvicorn.Server(config).serve()
