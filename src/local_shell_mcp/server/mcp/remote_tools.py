"""MCP tool registration for remote-worker proxy tools."""

import inspect
import re

from mcp.server.fastmcp import FastMCP

from ...ops.remote import remote_admin_execute
from ...schemas.input_models.remote import (
    RemoteAdminActionArg,
    RemoteAdminArgsArg,
)
from ...schemas.result_models.remote import (
    RemoteAdminOutput,
)
from ...tools.contracts import McpToolContext


def _description(text: str) -> str:
    """Return a clean MCP tool description from source text."""
    paragraphs = re.split(r"\n\s*\n", inspect.cleandoc(text))
    return "\n\n".join(
        " ".join(paragraph.split())
        for paragraph in paragraphs
        if paragraph.split()
    )


def register_remote_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    settings = context.settings
    remote_admin_meta = context.scoped_oauth_security_meta(("remote:use",))

    @mcp.tool(
        structured_output=True,
        meta=remote_admin_meta,
        description=_description(
            f"""Run compact remote control-plane actions. Use action="list" to discover worker names; action="invite" to create a one-time join command; action="revoke" to remove a stale or untrusted worker; and action="rename" to give a worker a stable name. Defaults: invite ttl_s defaults to the configured remote_invite_ttl_s={settings.remote_invite_ttl_s} seconds when omitted. Security: treat invite output as sensitive because it grants enrollment capability."""
        ),
    )
    async def remote_admin(
        action: RemoteAdminActionArg,
        args: RemoteAdminArgsArg,
    ) -> RemoteAdminOutput:
        """Run a remote control-plane action."""
        return await remote_admin_execute(action, args)
