"""Build and run the MCP ASGI/stdio application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .auth.middleware import AuthMiddleware
from .auth.oauth import (
    oauth_authorize_get,
    oauth_authorize_post,
    oauth_protected_resource,
    oauth_register,
    oauth_server_metadata,
    oauth_token,
)
from .config.settings import get_settings, validate_public_oauth_configuration
from .remote import remote_routes
from .tools import build_mcp


def with_oauth_routes(inner_app: Any) -> Starlette:
    """Wrap the MCP ASGI app with health, OAuth, and remote-worker routes."""

    @asynccontextmanager
    async def lifespan(app: Starlette):  # noqa: ARG001
        async with inner_app.router.lifespan_context(inner_app):
            yield

    routes = [
        Route(
            "/healthz",
            lambda request: JSONResponse({"ok": True}),  # noqa: ARG005
            methods=["GET"],
        ),
        Route(
            "/readyz",
            lambda request: JSONResponse({"ok": True}),  # noqa: ARG005
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource",
            oauth_protected_resource,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            oauth_server_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/openid-configuration",
            oauth_server_metadata,
            methods=["GET"],
        ),
        Route("/oauth/register", oauth_register, methods=["POST"]),
        Route("/oauth/authorize", oauth_authorize_get, methods=["GET"]),
        Route("/oauth/authorize", oauth_authorize_post, methods=["POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Mount("/", app=inner_app),
    ]
    settings = get_settings()
    if settings.remote_enabled:
        routes[2:2] = remote_routes()
    return Starlette(routes=routes, lifespan=lifespan)


def build_mcp_http_app(mcp: Any | None = None) -> Starlette | None:
    """Build the MCP HTTP ASGI app for the current settings and SDK version."""
    settings = get_settings()
    mcp = mcp or build_mcp()
    for attr in ("streamable_http_app", "sse_app"):
        if hasattr(mcp, attr):
            inner = getattr(mcp, attr)()
            app = with_oauth_routes(inner)
            if settings.auth_mode != "none":
                app.add_middleware(AuthMiddleware)
            return app
    return None


def run_mcp() -> None:
    """Run the FastMCP server through stdio or HTTP transport."""
    settings = get_settings()
    validate_public_oauth_configuration(settings)
    mcp = build_mcp()

    if settings.mode == "stdio":
        mcp.run(transport="stdio")
        return

    app = build_mcp_http_app(mcp)
    if app is not None:
        uvicorn.run(app, host=settings.host, port=settings.port)
        return

    # Fallback for older MCP SDKs. OAuth metadata cannot be attached in this mode,
    # so this is suitable only for localhost/stdio-style testing.
    try:
        mcp.run(transport="streamable-http")
    except TypeError:
        mcp.run(transport="sse")
