"""Remote-worker tool registry."""

from collections.abc import Iterable, Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...config.settings import Settings
from ...ops.remote import (
    remote_admin_execute,
    remote_worker_tool_execute,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
from ...schemas.input_models.remote import (
    RemoteAdminActionArg,
    RemoteAdminArgsArg,
)
from ...schemas.result_models.remote import (
    RemoteAdminOutput,
    RemoteWorkerToolOutput,
)
from ..contracts import HttpToolRoute, McpToolContext, ToolHandler
from ..declarative import DeclarativeToolRegistry


def _remote_tools_enabled(settings: Settings) -> bool:
    return settings.remote_enabled and settings.mode == "mcp"


class RemoteToolRegistry(DeclarativeToolRegistry):
    """Register remote-worker control-plane tools."""

    name = "remote"
    """Registry group name used for tool-surface organization."""

    def http_routes(self) -> Iterable[HttpToolRoute]:
        """Return public remote REST routes when remote tools are enabled."""
        if not _remote_tools_enabled(self._settings()):
            return ()
        return (*super().http_routes(), *REMOTE_WORKER_HTTP_ROUTES)

    def http_handlers(self) -> Mapping[str, ToolHandler]:
        """Return public remote HTTP handlers when remote tools are enabled."""
        if not _remote_tools_enabled(self._settings()):
            return {}
        return {**super().http_handlers(), **REMOTE_WORKER_HTTP_HANDLERS}

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        """Register declarative remote MCP tools when remote tools are enabled."""
        if not _remote_tools_enabled(context.settings):
            return
        super().register_mcp(mcp, context)


remote_tool = RemoteToolRegistry.get_tool_decorator()


def _remote_admin_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Run compact remote-worker control-plane actions. Use this only to administer worker connections: action=\"list\" discovers connected worker names for session_start(target=\"remote\", machine=...), action=\"invite\" creates a one-time join command, action=\"revoke\" removes a stale or untrusted worker, and action=\"rename\" gives a worker a stable name.

Do not use remote_admin for normal remote code work. For that, create a remote agent/workspace session with session_start(target=\"remote\", machine=..., workdir=...) and then use ordinary session-bound tools such as read, search, hashline_edit, edit_lines, bash, job, write_file, delete_file_or_dir, tree_view, glob_search, and secret_scan. Invite output is sensitive because it grants enrollment capability. Defaults: invite ttl_s defaults to configured remote_invite_ttl_s={settings.remote_invite_ttl_s} seconds when omitted."""


@remote_tool(
    http_method="POST",
    http_path="/tools/remote_admin",
    description=_remote_admin_description,
    oauth_scopes=("remote:use",),
)
async def remote_admin(
    action: RemoteAdminActionArg,
    args: RemoteAdminArgsArg,
) -> RemoteAdminOutput:
    """Run a remote-worker control-plane action."""
    return await remote_admin_execute(action, args)


def _make_remote_worker_handler(
    tool_name: str,
    *,
    timeout_arg: str | None = None,
    default_timeout: int | None = None,
) -> ToolHandler:
    """Build an HTTP handler for a proxied remote-worker primitive."""

    async def handler(args: dict[str, Any]) -> RemoteWorkerToolOutput:
        timeout_s = (
            args.get(timeout_arg, default_timeout)
            if timeout_arg is not None
            else None
        )
        return await remote_worker_tool_execute(args, tool_name, timeout_s)

    return handler


REMOTE_WORKER_HTTP_ROUTES = tuple(
    HttpToolRoute("POST", spec.http_path, spec.public_name)
    for spec in REMOTE_WORKER_TOOL_SPECS
    if spec.expose_http and spec.http_path is not None
)
REMOTE_WORKER_HTTP_HANDLERS = {
    spec.public_name: _make_remote_worker_handler(
        spec.worker_tool,
        timeout_arg=spec.timeout_arg,
        default_timeout=spec.default_timeout,
    )
    for spec in REMOTE_WORKER_TOOL_SPECS
    if spec.expose_http
}
