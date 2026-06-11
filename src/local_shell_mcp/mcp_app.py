"""Build and run the MCP ASGI/stdio application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlparse

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


def _host_header_name(hostname: str) -> str:
    """Return a Host-header-safe hostname, adding IPv6 brackets when needed."""
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]"
    return hostname


def _default_port_for_scheme(scheme: str) -> int | None:
    """Return the default network port for schemes accepted in public_base_url."""
    return {"http": 80, "https": 443}.get(scheme)


def _add_public_base_url_transport_allowlist(
    allowed_hosts: set[str], allowed_origins: set[str], public_base_url: str
) -> None:
    """Allow exactly the configured public origin and compatible default-port Host forms."""
    parsed = urlparse(public_base_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return

    try:
        port = parsed.port
    except ValueError:
        return

    host = _host_header_name(parsed.hostname.lower())
    default_port = _default_port_for_scheme(scheme)

    if port is None:
        allowed_hosts.add(host)
        if default_port is not None:
            allowed_hosts.add(f"{host}:{default_port}")
        allowed_origins.add(f"{scheme}://{host}")
        return

    allowed_hosts.add(f"{host}:{port}")
    if port == default_port:
        allowed_hosts.add(host)
        allowed_origins.add(f"{scheme}://{host}")
    else:
        allowed_origins.add(f"{scheme}://{host}:{port}")


def _transport_security_settings() -> TransportSecuritySettings:
    """Derive transport-specific auth metadata from the active server settings."""
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
        _add_public_base_url_transport_allowlist(
            allowed_hosts, allowed_origins, settings.public_base_url
        )

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(allowed_hosts),
        allowed_origins=sorted(allowed_origins),
    )


SERVER_INSTRUCTIONS = """You are operating local-shell-mcp, a coding-agent control surface for the configured workspace/container and optional remote workers.

Work carefully and prefer small, inspectable steps:
- Use search, tree_view, glob_search, grep_search, read_file, and read_many_files to inspect before editing.
- Use edit_file or multi_edit_file for precise local text replacements, and apply_patch for larger local diffs. Use remote_* equivalents for connected remote workers.
- Use run_shell_tool for bounded one-shot shell commands, including git workflows. Dedicated git tools are intentionally not exposed. Use shell_start/shell_send/shell_read for long-running, streaming, or interactive local processes.
- For remote workers, first use remote_list_machines or remote_environment_info when needed, then use remote_run_shell_tool for bounded one-shot remote commands, including remote git workflows. Use remote_shell_start/shell_send/shell_read for long-running or interactive remote processes.
- Before committing, pushing, releasing, or sharing logs, inspect diffs and consider secret_scan. secret_scan is heuristic and does not prove a workspace is secret-free.
- Respect workspace/path restrictions and runtime limits advertised by each tool description. Do not assume full-container access unless the environment reports it.
- Keep the user informed about meaningful progress during longer multi-step work, and report validation commands and results clearly.
"""


def build_mcp() -> FastMCP:
    """Create the configured FastMCP server from discovered tool registries."""
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp",
        instructions=SERVER_INSTRUCTIONS,
        transport_security=_transport_security_settings(),
    )
    read_only_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    # Tool-level securitySchemes are client-facing MCP metadata only. Actual
    # HTTP/MCP authentication is enforced by AuthMiddleware at the transport
    # boundary, not by these per-tool advertisements.
    context = McpToolContext(
        settings=settings,
        read_only_tool=read_only_tool,
        connector_meta=security_meta(
            [*NOAUTH_SECURITY_SCHEMES, *OAUTH_SECURITY_SCHEMES]
        ),
        protected_meta=security_meta(OAUTH_SECURITY_SCHEMES),
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
