"""Build and run the MCP ASGI/stdio application."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
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
from .config.settings import get_settings
from .remote import remote_routes
from .tools.base import McpToolContext
from .tools.discovery import discover_tool_registries
from .tools.registry.common import (
    NOAUTH_SECURITY_SCHEMES,
    OAUTH_SECURITY_SCHEMES,
    handled_error,
    install_full_container_auto_approval_hints,
    install_mcp_tool_watchdogs,
    ok_response,
    security_meta,
)


def _transport_security_settings() -> TransportSecuritySettings:
    """Derive transport-specific auth metadata from the active server settings."""
    from urllib.parse import urlparse

    settings = get_settings()
    allowed_hosts = {
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "[::1]",
        "[::1]:*",
    }
    allowed_origins = {
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
        "https://chatgpt.com",
        "https://chat.openai.com",
    }

    if settings.public_base_url:
        parsed = urlparse(settings.public_base_url)
        if parsed.netloc:
            allowed_hosts.add(parsed.netloc)
            allowed_hosts.add(f"{parsed.hostname}:*")
            allowed_origins.add(f"{parsed.scheme}://{parsed.netloc}")

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(allowed_hosts),
        allowed_origins=sorted(allowed_origins),
    )


def build_mcp() -> FastMCP:
    """Create the configured FastMCP server from discovered tool registries."""
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp", transport_security=_transport_security_settings()
    )
    read_only_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    context = McpToolContext(
        settings=settings,
        read_only_tool=read_only_tool,
        read_only_meta=security_meta(
            [*NOAUTH_SECURITY_SCHEMES, *OAUTH_SECURITY_SCHEMES]
        ),
        oauth_meta=security_meta(OAUTH_SECURITY_SCHEMES),
        ok=ok_response,
        handled_error=handled_error,
    )
    for registry in discover_tool_registries():
        registry.register_mcp(mcp, context)
    install_full_container_auto_approval_hints(mcp)
    install_mcp_tool_watchdogs(mcp)
    return mcp


def with_oauth_routes(inner_app: Starlette) -> Starlette:
    """Wrap the MCP ASGI app with health, OAuth, and remote-worker routes."""

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with inner_app.router.lifespan_context(inner_app):
            yield

    routes = [
        Route(
            "/healthz",
            lambda request: JSONResponse({"ok": True}),
            methods=["GET"],
        ),
        Route(
            "/readyz",
            lambda request: JSONResponse({"ok": True}),
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


def build_mcp_http_app(mcp: FastMCP) -> Starlette:
    """Build the MCP HTTP ASGI app for the current settings and SDK version."""
    settings = get_settings()
    for attr in ("streamable_http_app", "sse_app"):
        if hasattr(mcp, attr):
            inner: Starlette = getattr(mcp, attr)()
            app = with_oauth_routes(inner)
            if settings.auth_mode != "none":
                app.add_middleware(AuthMiddleware)
            return app
    raise RuntimeError(
        "MCP HTTP ASGI app not available since both streamable_http_app and sse_app are not available"
    )


def run_mcp() -> None:
    """Run the FastMCP server through stdio or HTTP transport."""
    settings = get_settings()
    mcp = build_mcp()

    if settings.mode == "stdio":
        # stdio do not need http service
        mcp.run(transport="stdio")
    else:
        app = build_mcp_http_app(mcp)
        uvicorn.run(app, host=settings.host, port=settings.port)
