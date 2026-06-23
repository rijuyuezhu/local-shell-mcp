"""MCP tool registration for remote-worker proxy tools."""

import inspect
import re

from mcp.server.fastmcp import FastMCP

from ...ops.remote import remote_admin_execute, remote_execute
from ...schemas.input_models.remote import (
    RemoteAdminActionArg,
    RemoteAdminArgsArg,
    RemoteFacadeArgsArg,
    RemoteFacadeOpArg,
    RemoteMachineArg,
)
from ...schemas.result_models.remote import (
    RemoteAdminOutput,
    RemoteFacadeOutput,
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
    remote_meta = context.scoped_oauth_security_meta(
        (
            "remote:use",
            "shell:read",
            "shell:write",
            "shell:execute",
            "git:write",
        )
    )

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

    @mcp.tool(
        structured_output=True,
        meta=remote_meta,
        description=_description(
            """Run work on a selected remote worker. Use this for remote reads, searches, line edits, shell commands, jobs, persistent-shell companion actions, transfers, and workspace operations. Use op to choose the operation and args for operation-specific parameters; do not include machine inside args. Use op="session_start" to create a worker-side agent/workspace session for remote bash/read/search/edit/job calls that require session_id. Use op="session" with args.action of send/read/kill/list and shell_id to manage persistent shells created by remote bash PTY work; shell_id is separate from the worker-side session_id. Use op="transfer" with args.action of push_file, pull_file, push_dir, pull_dir, copy_file, or copy_dir for binary-safe movement. Use remote_admin for invite/list/revoke/rename control-plane work."""
        ),
    )
    async def remote(
        machine: RemoteMachineArg,
        op: RemoteFacadeOpArg,
        args: RemoteFacadeArgsArg,
    ) -> RemoteFacadeOutput:
        """Run a high-level operation on a remote worker."""
        return await remote_execute(machine, op, args)
