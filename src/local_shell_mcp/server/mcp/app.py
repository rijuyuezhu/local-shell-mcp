"""Build and run the MCP server."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.routing import BaseRoute, Mount

from ...config.settings import get_settings
from ...oauth.middleware import AuthMiddleware
from ...oauth.routes import oauth_public_routes
from ...remote.http import remote_routes
from ...tools.contracts import McpToolContext
from ...tools.discovery import discover_tool_registries
from ..shared.public_routes import public_http_routes
from .instructions import SERVER_INSTRUCTIONS
from .metadata import (
    connector_compatible_security_meta,
    install_full_container_auto_approval_hints,
    oauth_security_meta,
    scoped_oauth_security_meta,
)
from .transport_security import transport_security_settings
from .watchdogs import install_mcp_tool_watchdogs


def _get_read_only_tool() -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def build_mcp() -> FastMCP:
    """Create the configured FastMCP server from discovered tool registries."""
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp",
        instructions=SERVER_INSTRUCTIONS,
        transport_security=transport_security_settings(),
    )
    # Tool-level securitySchemes are client-facing MCP metadata only. Actual
    # HTTP/MCP authentication is enforced by AuthMiddleware at the transport
    # boundary, not by these per-tool advertisements. The noauth-or-oauth
    # profile exists only for connector-compatible read-only search/fetch
    # clients; it is not a server-side auth bypass.
    context = McpToolContext(
        settings=settings,
        read_only_tool=_get_read_only_tool(),
        connector_compatible_security_meta=connector_compatible_security_meta(),
        oauth_security_meta=oauth_security_meta(),
        scoped_oauth_security_meta=scoped_oauth_security_meta,
    )
    for registry in discover_tool_registries():
        registry.register_mcp(mcp, context)
    install_full_container_auto_approval_hints(mcp)
    install_mcp_tool_watchdogs(mcp)
    return mcp


def _wrap_mcp_http_app(inner_app: Starlette) -> Starlette:
    """Wrap the SDK MCP ASGI app with public routes before mounting it."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        async with inner_app.router.lifespan_context(inner_app):
            yield

    public_routes: list[BaseRoute] = [
        *public_http_routes(
            settings,
            readyz_include_workspace_root=False,
        ),
        *(remote_routes() if settings.remote_enabled else ()),
        *oauth_public_routes(),
    ]
    routes = [*public_routes, Mount("/", app=inner_app)]
    return Starlette(routes=routes, lifespan=lifespan)


def _build_mcp_http_transport_app(inner_app: Starlette) -> Starlette:
    """Build one MCP HTTP transport app from a FastMCP SDK ASGI app."""
    settings = get_settings()
    app = _wrap_mcp_http_app(inner_app)
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware, public_routes=app.routes[:-1])
    return app


def build_mcp_http_app(mcp: FastMCP) -> Starlette:
    """Build the MCP HTTP ASGI app for the current settings and SDK version."""
    for attr in ("streamable_http_app", "sse_app"):
        if hasattr(mcp, attr):
            inner: Starlette = getattr(mcp, attr)()
            return _build_mcp_http_transport_app(inner)
    raise RuntimeError(
        "MCP HTTP ASGI app not available since both streamable_http_app and sse_app are not available"
    )


def run_mcp() -> None:
    """Run the FastMCP server."""
    settings = get_settings()
    mcp = build_mcp()

    if settings.mode == "stdio":
        # stdio do not need http service
        mcp.run(transport="stdio")
    else:
        app = build_mcp_http_app(mcp)
        uvicorn.run(app, host=settings.host, port=settings.port)
