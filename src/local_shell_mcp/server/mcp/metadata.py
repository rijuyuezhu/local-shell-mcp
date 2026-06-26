"""Client-facing tool metadata and approval-hint helpers."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...config.settings import get_settings
from ...oauth.core.scopes import dedupe_scopes


def oauth_security_scheme(
    scopes: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Return one OAuth MCP security scheme for the provided scopes."""
    return {"type": "oauth2", "scopes": dedupe_scopes(scopes)}


# Client-facing hint used by connector-compatible read-only search/fetch tools.
# This does not bypass AuthMiddleware or per-tool scope checks; it only helps
# connector-style clients discover these tools as a document-source surface.
NOAUTH_SECURITY_SCHEME = {"type": "noauth"}


def oauth_security_meta(
    scopes: list[str] | tuple[str, ...],
    *,
    connector_compatible: bool = False,
) -> dict[str, Any]:
    """Return MCP securitySchemes metadata for server-enforced OAuth scopes."""
    schemes = [oauth_security_scheme(scopes)]
    if connector_compatible:
        schemes.insert(0, NOAUTH_SECURITY_SCHEME)
    return {"securitySchemes": schemes}


def install_full_container_auto_approval_hints(mcp: FastMCP) -> None:
    """Patch local tool schemas to advertise reduced MCP client confirmation needs. Usually this may reduce confirmation prompts for mutating tools on the client.

    These are client-facing hints only. They do not change server-side authentication, authorization, workspace boundaries, command policy, or audit behavior, and they intentionally do not mark mutating tools as read-only.
    """
    settings = get_settings()
    if not (settings.allow_full_control or settings.relaxed_client_tool_hints):
        return
    for tool in mcp._tool_manager._tools.values():
        # TODO: shall we skip such tools?
        if tool.name == "call_agent_mcp_tool" or tool.name.startswith(
            "agent_mcp__"
        ):
            continue
        if tool.annotations and tool.annotations.readOnlyHint:
            continue
        tool.annotations = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        )
