"""Remote worker MCP tool registry."""

from collections.abc import Iterable, Mapping
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ...config.settings import Settings
from ...mcp.remote_tools import register_remote_mcp
from ...remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
from ...remote.transfer import (
    copy_local_dir_to_remote,
    copy_local_file_to_remote,
    copy_remote_dir_to_local,
    copy_remote_dir_to_remote,
    copy_remote_file_to_local,
    copy_remote_file_to_remote,
)
from ..contracts import HttpToolRoute, McpToolContext, ToolHandler
from ..declarative import DeclarativeToolRegistry


def _remote_tools_enabled(settings: Settings) -> bool:
    return settings.remote_enabled and settings.mode == "mcp"


class RemoteToolRegistry(DeclarativeToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"

    def http_routes(self) -> Iterable[HttpToolRoute]:
        if not _remote_tools_enabled(self._settings()):
            return ()
        return (*super().http_routes(), *REMOTE_WORKER_HTTP_ROUTES)

    def http_handlers(self) -> Mapping[str, ToolHandler]:
        if not _remote_tools_enabled(self._settings()):
            return {}
        return {**super().http_handlers(), **REMOTE_WORKER_HTTP_HANDLERS}

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        if not _remote_tools_enabled(context.settings):
            return
        register_remote_mcp(mcp, context)


local_tool = RemoteToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/remote_invite")
async def remote_invite(
    name: str | None = None,
    workdir: str | None = None,
    ttl_s: int | None = None,
) -> dict[str, Any]:
    """Create a one-time command for a remote worker to join this control server. Parameters: name is an optional friendly worker name; workdir is the worker starting directory; ttl_s is invite lifetime in seconds."""
    return await create_remote_invite(name, workdir, ttl_s)


@local_tool(http_method="GET", http_path="/tools/remote_list_machines")
async def remote_list_machines() -> dict[str, Any]:
    """List remote worker machines currently known to the control server."""
    return list_remote_machines()


@local_tool(http_method="POST", http_path="/tools/remote_revoke_machine")
async def remote_revoke_machine(machine: str) -> dict[str, Any]:
    """Revoke and remove a remote worker machine. Parameter machine must be an exact name from remote_list_machines; use when a worker is stale or should no longer receive jobs."""
    return revoke_remote_machine(machine)


@local_tool(http_method="POST", http_path="/tools/remote_rename_machine")
async def remote_rename_machine(machine: str, new_name: str) -> dict[str, Any]:
    """Rename a remote worker machine. Parameters: machine is the current exact name from remote_list_machines; new_name is the stable name to use for later remote_* calls."""
    return rename_remote_machine(machine, new_name)


def _remote_worker_args(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key != "machine"}


async def _remote_worker_tool(
    args: dict[str, Any], tool_name: str, timeout_s: int | None = None
) -> dict[str, Any]:
    machine = args.get("machine")
    if machine is None:
        raise ValueError("Missing required argument: machine")
    result = await call_remote_worker_tool(
        str(machine), tool_name, _remote_worker_args(args), timeout_s
    )
    if result.get("ok", False):
        data = result.get("data")
        return (
            cast(dict[str, Any], data)
            if isinstance(data, dict)
            else {"result": data}
        )
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


@local_tool(http_method="POST", http_path="/tools/remote_copy_file")
async def remote_copy_file(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Copy one file between two remote worker machines through the control server. src_machine and dst_machine are exact names from remote_list_machines; src_path is the source file; dst_path is the target file; overwrite controls replacing an existing target; chunk_size usually should be omitted."""
    return await copy_remote_file_to_remote(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_copy_dir")
async def remote_copy_dir(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Copy a directory tree between two remote worker machines through the control server. src_machine and dst_machine are exact names from remote_list_machines; src_path is the source directory; dst_path is the target directory; overwrite controls replacing an existing target; chunk_size usually should be omitted."""
    return await copy_remote_dir_to_remote(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_pull_file")
async def remote_pull_file(
    machine: str,
    remote_path: str,
    local_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Copy one file from a remote worker to the control server workspace. machine is the exact name from remote_list_machines; remote_path is the source file on that worker; local_path is the local target file; overwrite controls replacing an existing local target; chunk_size usually should be omitted."""
    return await copy_remote_file_to_local(
        machine, remote_path, local_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_push_file")
async def remote_push_file(
    local_path: str,
    machine: str,
    remote_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Copy one file from the control server workspace to a remote worker. local_path is the local source file; machine is the exact name from remote_list_machines; remote_path is the target file on that worker; overwrite controls replacing an existing remote target; chunk_size usually should be omitted."""
    return await copy_local_file_to_remote(
        local_path, machine, remote_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_pull_dir")
async def remote_pull_dir(
    machine: str,
    remote_path: str,
    local_path: str,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Copy a directory tree from a remote worker to the control server workspace. machine is the exact name from remote_list_machines; remote_path is the source directory on that worker; local_path is the local target directory; overwrite controls replacing an existing local target; chunk_size usually should be omitted."""
    return await copy_remote_dir_to_local(
        machine, remote_path, local_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_push_dir")
async def remote_push_dir(
    local_path: str,
    machine: str,
    remote_path: str,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Copy a directory tree from the control server workspace to a remote worker. local_path is the local source directory; machine is the exact name from remote_list_machines; remote_path is the target directory on that worker; overwrite controls replacing an existing remote target; chunk_size usually should be omitted."""
    return await copy_local_dir_to_remote(
        local_path, machine, remote_path, overwrite, chunk_size
    )


REMOTE_WORKER_HTTP_ROUTES = tuple(
    HttpToolRoute("POST", spec.http_path, spec.public_name)
    for spec in REMOTE_WORKER_TOOL_SPECS
    if spec.expose_http and spec.http_path is not None
)

REMOTE_WORKER_HTTP_HANDLERS: dict[str, ToolHandler] = {
    spec.public_name: _make_remote_worker_handler(
        spec.worker_tool,
        timeout_arg=spec.timeout_arg,
        default_timeout=spec.default_timeout,
    )
    for spec in REMOTE_WORKER_TOOL_SPECS
    if spec.expose_http
}
