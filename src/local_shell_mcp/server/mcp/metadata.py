"""Client-facing tool metadata and approval-hint helpers."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...config.settings import get_settings
from ...oauth.scopes import (
    SCOPE_SHELL_READ,
    SUPPORTED_OAUTH_SCOPES,
    dedupe_scopes,
)


def oauth_security_scheme(
    scopes: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Return one OAuth MCP security scheme for the provided scopes."""
    return {"type": "oauth2", "scopes": dedupe_scopes(scopes)}


def oauth_security_meta(scopes: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Return MCP security metadata for one OAuth scope set."""
    return security_meta([oauth_security_scheme(scopes)])


OAUTH_SECURITY_SCHEMES = [oauth_security_scheme(SUPPORTED_OAUTH_SCOPES)]
# Client-facing hint used by connector-compatible read-only search/fetch tools.
# This does not bypass AuthMiddleware; it only helps connector-style clients
# discover these tools as a document-source style search/fetch surface.
NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]


def security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach client-facing MCP securitySchemes metadata to a tool."""
    return {"securitySchemes": schemes}


def connector_compatible_security_meta() -> dict[str, Any]:
    """Return MCP metadata for connector-compatible read-only search/fetch tools."""
    return security_meta(
        [NOAUTH_SECURITY_SCHEMES[0], oauth_security_scheme((SCOPE_SHELL_READ,))]
    )


def install_full_container_auto_approval_hints(mcp: FastMCP) -> None:
    """Patch local tool schemas to advertise reduced MCP client confirmation needs. Usually this may reduce confirmation prompts for mutating tools on the client.

    These are client-facing hints only. They do not change server-side
    authentication, authorization, workspace boundaries, command policy, or audit
    behavior, and they intentionally do not mark mutating tools as read-only.
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
