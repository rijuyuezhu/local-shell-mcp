"""Remote-worker tool registry."""

from collections.abc import Iterable, Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...config.settings import Settings
from ...ops.remote import (
    remote_admin_execute,
    remote_execute,
    remote_worker_tool_execute,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
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
    RemoteWorkerToolOutput,
)
from ...server.mcp.remote_tools import register_remote_mcp
from ..contracts import HttpToolRoute, McpToolContext, ToolHandler
from ..declarative import DeclarativeToolRegistry


def _remote_tools_enabled(settings: Settings) -> bool:
    return settings.remote_enabled and settings.mode == "mcp"


class RemoteToolRegistry(DeclarativeToolRegistry):
    """Register compact remote-worker tools."""

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
        """Register remote MCP tools when remote tools are enabled."""
        if not _remote_tools_enabled(context.settings):
            return
        register_remote_mcp(mcp, context)


local_tool = RemoteToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/remote")
async def remote(
    machine: RemoteMachineArg,
    op: RemoteFacadeOpArg,
    args: RemoteFacadeArgsArg,
) -> RemoteFacadeOutput:
    """Run work on a selected remote worker. Use this for remote read, search, edit_lines, bash/python, jobs, worker-side session_start, persistent shells, transfers, and workspace operations. Use remote_admin for invite/list/revoke/rename control-plane work. Keep remote edits grounded by remote read/search snapshots just like local edits."""
    return await remote_execute(machine, op, args)


@local_tool(http_method="POST", http_path="/tools/remote_admin")
async def remote_admin(
    action: RemoteAdminActionArg,
    args: RemoteAdminArgsArg,
) -> RemoteAdminOutput:
    """Run a compact remote control-plane action. Use action="list" to discover connected workers, action="invite" to create a join command, action="revoke" to remove a worker, and action="rename" to give a worker a stable name."""
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
