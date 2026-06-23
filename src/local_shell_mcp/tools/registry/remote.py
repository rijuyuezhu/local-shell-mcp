"""Remote worker MCP tool registry."""

from collections.abc import Iterable, Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...config.settings import Settings
from ...ops.remote import (
    remote_copy_dir_execute,
    remote_copy_file_execute,
    remote_execute,
    remote_invite_execute,
    remote_list_machines_execute,
    remote_pull_dir_execute,
    remote_pull_file_execute,
    remote_push_dir_execute,
    remote_push_file_execute,
    remote_rename_machine_execute,
    remote_revoke_machine_execute,
    remote_worker_tool_execute,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
from ...schemas.input_models.remote import (
    LocalPathArg,
    RemoteChunkSizeArg,
    RemoteDestinationMachineArg,
    RemoteDestinationPathArg,
    RemoteFacadeArgsArg,
    RemoteFacadeOpArg,
    RemoteInviteNameArg,
    RemoteInviteTtlArg,
    RemoteMachineArg,
    RemoteNewNameArg,
    RemoteOverwriteArg,
    RemotePathArg,
    RemoteSourceMachineArg,
    RemoteSourcePathArg,
    RemoteWorkdirArg,
)
from ...schemas.result_models.remote import (
    RemoteCopyDirOutput,
    RemoteCopyFileOutput,
    RemoteFacadeOutput,
    RemoteInviteOutput,
    RemoteListMachinesOutput,
    RemoteRenameMachineOutput,
    RemoteRevokeMachineOutput,
    RemoteWorkerToolOutput,
)
from ...server.mcp.remote_tools import register_remote_mcp
from ..contracts import HttpToolRoute, McpToolContext, ToolHandler
from ..declarative import DeclarativeToolRegistry


def _remote_tools_enabled(settings: Settings) -> bool:
    return settings.remote_enabled and settings.mode == "mcp"


class RemoteToolRegistry(DeclarativeToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"
    """Registry group name used for tool-surface organization."""

    def http_routes(self) -> Iterable[HttpToolRoute]:
        """Return remote REST proxy routes when remote tools are enabled."""
        if not _remote_tools_enabled(self._settings()):
            return ()
        return (*super().http_routes(), *REMOTE_WORKER_HTTP_ROUTES)

    def http_handlers(self) -> Mapping[str, ToolHandler]:
        """Return remote HTTP proxy handlers when remote tools are enabled."""
        if not _remote_tools_enabled(self._settings()):
            return {}
        return {**super().http_handlers(), **REMOTE_WORKER_HTTP_HANDLERS}

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        """Register remote MCP proxy tools when remote tools are enabled."""
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
    """Run a semantic operation on a selected remote worker. Prefer this facade for normal remote read, search, edit_lines, bash/python, jobs, and workspace operations. Use remote_list_machines for discovery, invite/revoke/rename for control-plane work, and transfer tools for data movement. Keep remote edits grounded by remote read/search snapshots just like local edits."""
    return await remote_execute(machine, op, args)


@local_tool(http_method="POST", http_path="/tools/remote_invite")
async def remote_invite(
    name: RemoteInviteNameArg = None,
    workdir: RemoteWorkdirArg = None,
    ttl_s: RemoteInviteTtlArg = None,
) -> RemoteInviteOutput:
    """Create a one-time command for a remote worker to join this control server. Parameters: name is an optional friendly worker name; workdir is the worker starting directory; ttl_s is invite lifetime in seconds."""
    return await remote_invite_execute(name, workdir, ttl_s)


@local_tool(http_method="GET", http_path="/tools/remote_list_machines")
async def remote_list_machines() -> RemoteListMachinesOutput:
    """List remote worker machines currently known to the control server."""
    return remote_list_machines_execute()


@local_tool(http_method="POST", http_path="/tools/remote_revoke_machine")
async def remote_revoke_machine(
    machine: RemoteMachineArg,
) -> RemoteRevokeMachineOutput:
    """Revoke and remove a remote worker machine. Parameter machine must be an exact name from remote_list_machines; use when a worker is stale or should no longer receive jobs."""
    return remote_revoke_machine_execute(machine)


@local_tool(http_method="POST", http_path="/tools/remote_rename_machine")
async def remote_rename_machine(
    machine: RemoteMachineArg, new_name: RemoteNewNameArg
) -> RemoteRenameMachineOutput:
    """Rename a remote worker machine. Parameters: machine is the current exact name from remote_list_machines; new_name is the stable name to use for later remote_* calls."""
    return remote_rename_machine_execute(machine, new_name)


def _make_remote_worker_handler(
    tool_name: str,
    *,
    timeout_arg: str | None = None,
    default_timeout: int | None = None,
) -> ToolHandler:
    """Build an HTTP handler for a proxied remote-worker tool."""

    async def handler(args: dict[str, Any]) -> RemoteWorkerToolOutput:
        timeout_s = (
            args.get(timeout_arg, default_timeout)
            if timeout_arg is not None
            else None
        )
        return await remote_worker_tool_execute(args, tool_name, timeout_s)

    return handler


@local_tool(http_method="POST", http_path="/tools/remote_copy_file")
async def remote_copy_file(
    src_machine: RemoteSourceMachineArg,
    src_path: RemoteSourcePathArg,
    dst_machine: RemoteDestinationMachineArg,
    dst_path: RemoteDestinationPathArg,
    overwrite: RemoteOverwriteArg = True,
    chunk_size: RemoteChunkSizeArg = None,
) -> RemoteCopyFileOutput:
    """Copy one file between two remote worker machines through the control server. src_machine and dst_machine are exact names from remote_list_machines; src_path is the source file; dst_path is the target file; overwrite controls replacing an existing target; chunk_size usually should be omitted."""
    return await remote_copy_file_execute(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_copy_dir")
async def remote_copy_dir(
    src_machine: RemoteSourceMachineArg,
    src_path: RemoteSourcePathArg,
    dst_machine: RemoteDestinationMachineArg,
    dst_path: RemoteDestinationPathArg,
    overwrite: RemoteOverwriteArg = False,
    chunk_size: RemoteChunkSizeArg = None,
) -> RemoteCopyDirOutput:
    """Copy a directory tree between two remote worker machines through the control server. src_machine and dst_machine are exact names from remote_list_machines; src_path is the source directory; dst_path is the target directory; overwrite controls replacing an existing target; chunk_size usually should be omitted."""
    return await remote_copy_dir_execute(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_pull_file")
async def remote_pull_file(
    machine: RemoteMachineArg,
    remote_path: RemotePathArg,
    local_path: LocalPathArg,
    overwrite: RemoteOverwriteArg = True,
    chunk_size: RemoteChunkSizeArg = None,
) -> RemoteCopyFileOutput:
    """Copy one file from a remote worker to the control server workspace. machine is the exact name from remote_list_machines; remote_path is the source file on that worker; local_path is the local target file; overwrite controls replacing an existing local target; chunk_size usually should be omitted."""
    return await remote_pull_file_execute(
        machine, remote_path, local_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_push_file")
async def remote_push_file(
    local_path: LocalPathArg,
    machine: RemoteMachineArg,
    remote_path: RemotePathArg,
    overwrite: RemoteOverwriteArg = True,
    chunk_size: RemoteChunkSizeArg = None,
) -> RemoteCopyFileOutput:
    """Copy one file from the control server workspace to a remote worker. local_path is the local source file; machine is the exact name from remote_list_machines; remote_path is the target file on that worker; overwrite controls replacing an existing remote target; chunk_size usually should be omitted."""
    return await remote_push_file_execute(
        local_path, machine, remote_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_pull_dir")
async def remote_pull_dir(
    machine: RemoteMachineArg,
    remote_path: RemotePathArg,
    local_path: LocalPathArg,
    overwrite: RemoteOverwriteArg = False,
    chunk_size: RemoteChunkSizeArg = None,
) -> RemoteCopyDirOutput:
    """Copy a directory tree from a remote worker to the control server workspace. machine is the exact name from remote_list_machines; remote_path is the source directory on that worker; local_path is the local target directory; overwrite controls replacing an existing local target; chunk_size usually should be omitted."""
    return await remote_pull_dir_execute(
        machine, remote_path, local_path, overwrite, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/remote_push_dir")
async def remote_push_dir(
    local_path: LocalPathArg,
    machine: RemoteMachineArg,
    remote_path: RemotePathArg,
    overwrite: RemoteOverwriteArg = False,
    chunk_size: RemoteChunkSizeArg = None,
) -> RemoteCopyDirOutput:
    """Copy a directory tree from the control server workspace to a remote worker. local_path is the local source directory; machine is the exact name from remote_list_machines; remote_path is the target directory on that worker; overwrite controls replacing an existing remote target; chunk_size usually should be omitted."""
    return await remote_push_dir_execute(
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
