"""Build and run the MCP server."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.routing import BaseRoute, Mount

from ...config.settings import get_settings
from ...oauth.http.middleware import AuthMiddleware
from ...oauth.http.routes import oauth_public_routes
from ...remote.http import remote_routes
from ...tools.contracts import McpToolContext
from ...tools.discovery import discover_tool_registries
from ..shared.public_routes import public_http_routes
from .instructions import SERVER_INSTRUCTIONS
from .metadata import install_full_container_auto_approval_hints
from .transport_security import transport_security_settings
from .watchdogs import install_mcp_tool_watchdogs


def _make_read_only_tool_annotations() -> ToolAnnotations:
    """Mark a tool as read-only for MCP clients."""
    return ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def build_mcp() -> FastMCP:
    """Create the MCP server and register the local tools."""
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp",
        instructions=SERVER_INSTRUCTIONS,
        transport_security=transport_security_settings(),
    )
    context = McpToolContext(
        settings=settings,
        read_only_tool_annotations=_make_read_only_tool_annotations(),
    )
    for registry in discover_tool_registries():
        registry.register_mcp(mcp, context)
    install_full_container_auto_approval_hints(mcp)
    install_mcp_tool_watchdogs(mcp)
    return mcp


def _add_public_routes_to_mcp_http_app(
    mcp_app: Starlette,
) -> tuple[Starlette, list[BaseRoute]]:
    """Serve health/OAuth routes directly and send everything else to MCP."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    public_routes: list[BaseRoute] = [
        *public_http_routes(
            settings,
            readyz_include_workspace_root=False,
        ),
        *(remote_routes() if settings.remote_enabled else ()),
        *oauth_public_routes(),
    ]
    routes = [*public_routes, Mount("/", app=mcp_app)]
    return Starlette(routes=routes, lifespan=lifespan), public_routes


def _build_authenticated_mcp_http_app(mcp_app: Starlette) -> Starlette:
    """Add OAuth protection around the MCP HTTP app when auth is enabled."""
    settings = get_settings()
    app, public_routes = _add_public_routes_to_mcp_http_app(mcp_app)
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware, public_routes=public_routes)
    return app


def build_mcp_http_app(mcp: FastMCP) -> Starlette:
    """Use the MCP SDK's HTTP app and add local public routes/auth."""
    for attr in ("streamable_http_app", "sse_app"):
        if hasattr(mcp, attr):
            inner: Starlette = getattr(mcp, attr)()
            return _build_authenticated_mcp_http_app(inner)
    raise RuntimeError(
        "MCP HTTP ASGI app not available since both streamable_http_app and sse_app are not available"
    )


def run_mcp() -> None:
    """Start the configured MCP server, over stdio or HTTP."""
    settings = get_settings()
    mcp = build_mcp()

    if settings.mode == "stdio":
        # stdio mode talks directly to the parent process; no HTTP app is needed.
        mcp.run(transport="stdio")
    else:
        app = build_mcp_http_app(mcp)
        uvicorn.run(app, host=settings.host, port=settings.port)
