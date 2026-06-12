"""Remote worker MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from .remote_mcp import register_remote_mcp


async def _remote_invite(args: dict[str, Any]) -> dict[str, Any]:
    return await create_remote_invite(
        args.get("name"), args.get("workdir"), args.get("ttl_s")
    )


async def _remote_list_machines(args: dict[str, Any]) -> dict[str, Any]:
    return list_remote_machines()


async def _remote_revoke_machine(args: dict[str, Any]) -> dict[str, Any]:
    return revoke_remote_machine(args["machine"])


async def _remote_rename_machine(args: dict[str, Any]) -> dict[str, Any]:
    return rename_remote_machine(args["machine"], args["new_name"])


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


REMOTE_CONTROL_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/remote_invite", "remote_invite"),
    HttpToolRoute("GET", "/tools/remote_list_machines", "remote_list_machines"),
    HttpToolRoute(
        "POST", "/tools/remote_revoke_machine", "remote_revoke_machine"
    ),
    HttpToolRoute(
        "POST", "/tools/remote_rename_machine", "remote_rename_machine"
    ),
)

REMOTE_HTTP_ROUTES = REMOTE_CONTROL_HTTP_ROUTES + tuple(
    HttpToolRoute("POST", spec.http_path, spec.public_name)
    for spec in REMOTE_WORKER_TOOL_SPECS
)

REMOTE_CONTROL_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "remote_invite": _remote_invite,
    "remote_list_machines": _remote_list_machines,
    "remote_revoke_machine": _remote_revoke_machine,
    "remote_rename_machine": _remote_rename_machine,
}

REMOTE_HTTP_HANDLERS: dict[str, ToolHandler] = {
    **REMOTE_CONTROL_HTTP_HANDLERS,
    **{
        spec.public_name: _make_remote_worker_handler(
            spec.worker_tool,
            timeout_arg=spec.timeout_arg,
            default_timeout=spec.default_timeout,
        )
        for spec in REMOTE_WORKER_TOOL_SPECS
    },
}


class RemoteToolRegistry(StaticHttpToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"

    routes = REMOTE_HTTP_ROUTES
    handlers = REMOTE_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_remote_mcp(mcp, context)
