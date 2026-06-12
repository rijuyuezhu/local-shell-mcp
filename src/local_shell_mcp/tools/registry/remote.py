"""Remote worker MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...mcp.remote_tools import register_remote_mcp
from ...remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
from ..base import HttpToolRoute, McpToolContext, ToolHandler
from ..definitions import DeclarativeToolRegistry


class RemoteToolRegistry(DeclarativeToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"

    def http_routes(self):
        return (*super().http_routes(), *REMOTE_WORKER_HTTP_ROUTES)

    def http_handlers(self):
        return {**super().http_handlers(), **REMOTE_WORKER_HTTP_HANDLERS}

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_remote_mcp(mcp, context)


local_tool = RemoteToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/remote_invite")
async def remote_invite(
    name: str | None = None,
    workdir: str | None = None,
    ttl_s: int | None = None,
) -> dict[str, Any]:
    """Create a one-time remote-worker invite."""
    return await create_remote_invite(name, workdir, ttl_s)


@local_tool(http_method="GET", http_path="/tools/remote_list_machines")
async def remote_list_machines() -> dict[str, Any]:
    """List remote worker machines currently known to the control server."""
    return list_remote_machines()


@local_tool(http_method="POST", http_path="/tools/remote_revoke_machine")
async def remote_revoke_machine(machine: str) -> dict[str, Any]:
    """Revoke and remove a remote worker machine."""
    return revoke_remote_machine(machine)


@local_tool(http_method="POST", http_path="/tools/remote_rename_machine")
async def remote_rename_machine(machine: str, new_name: str) -> dict[str, Any]:
    """Rename a remote worker machine."""
    return rename_remote_machine(machine, new_name)


def _remote_worker_args(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key != "machine"}


async def _remote_worker_tool(
    args: dict[str, Any], tool_name: str, timeout_s: int | None = None
) -> dict[str, Any]:
    result = await call_remote_worker_tool(
        args["machine"], tool_name, _remote_worker_args(args), timeout_s
    )
    if result.get("ok", False):
        data = result.get("data")
        return data if isinstance(data, dict) else {"result": data}
    return result


def _make_remote_worker_handler(
    tool_name: str,
    *,
    timeout_arg: str | None = None,
    default_timeout: int | None = None,
) -> ToolHandler:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        timeout_s = (
            args.get(timeout_arg, default_timeout)
            if timeout_arg is not None
            else None
        )
        return await _remote_worker_tool(args, tool_name, timeout_s)

    return handler


REMOTE_WORKER_HTTP_ROUTES = tuple(
    HttpToolRoute("POST", spec.http_path, spec.public_name)
    for spec in REMOTE_WORKER_TOOL_SPECS
)

REMOTE_WORKER_HTTP_HANDLERS: dict[str, ToolHandler] = {
    spec.public_name: _make_remote_worker_handler(
        spec.worker_tool,
        timeout_arg=spec.timeout_arg,
        default_timeout=spec.default_timeout,
    )
    for spec in REMOTE_WORKER_TOOL_SPECS
}
