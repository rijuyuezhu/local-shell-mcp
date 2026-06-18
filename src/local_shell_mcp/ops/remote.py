"""Remote worker operation helpers used by the remote tool registry."""

from typing import Any, cast

from ..remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ..remote.transfer import (
    copy_local_dir_to_remote,
    copy_local_file_to_remote,
    copy_remote_dir_to_local,
    copy_remote_dir_to_remote,
    copy_remote_file_to_local,
    copy_remote_file_to_remote,
)
from ..schemas.result_models.remote import (
    RemoteCopyDirOutput,
    RemoteCopyFileOutput,
    RemoteInviteOutput,
    RemoteListMachinesOutput,
    RemoteRenameMachineOutput,
    RemoteRevokeMachineOutput,
    RemoteWorkerToolOutput,
)


async def remote_invite_execute(
    name: str | None = None,
    workdir: str | None = None,
    ttl_s: int | None = None,
) -> RemoteInviteOutput:
    """Create a one-time join command for a remote worker."""
    return await create_remote_invite(name, workdir, ttl_s)


def remote_list_machines_execute() -> RemoteListMachinesOutput:
    """List remote worker machines known to the control server."""
    return list_remote_machines()


def remote_revoke_machine_execute(machine: str) -> RemoteRevokeMachineOutput:
    """Revoke and remove one remote worker machine by exact name."""
    return revoke_remote_machine(machine)


def remote_rename_machine_execute(
    machine: str, new_name: str
) -> RemoteRenameMachineOutput:
    """Rename one remote worker machine by exact current name."""
    return rename_remote_machine(machine, new_name)


def _remote_worker_args(args: dict[str, Any]) -> dict[str, Any]:
    """Strip control-server-only arguments before proxying to a worker."""
    return {key: value for key, value in args.items() if key != "machine"}


async def remote_worker_tool_execute(
    args: dict[str, Any], tool_name: str, timeout_s: int | None = None
) -> RemoteWorkerToolOutput:
    """Call one tool on a selected remote worker and normalize its output."""
    machine = args.get("machine")
    if machine is None:
        raise ValueError("Missing required argument: machine")
    result = await call_remote_worker_tool(
        str(machine), tool_name, _remote_worker_args(args), timeout_s
    )
    if result.get("ok", False):
        data = result.get("data")
        return RemoteWorkerToolOutput.model_validate(
            cast(dict[str, Any], data)
            if isinstance(data, dict)
            else {"result": data}
        )
    return RemoteWorkerToolOutput.model_validate(result)


async def remote_copy_file_execute(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyFileOutput:
    """Copy one file between two remote workers through the control server."""
    return await copy_remote_file_to_remote(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size
    )


async def remote_copy_dir_execute(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> RemoteCopyDirOutput:
    """Copy a directory tree between two remote workers through the control server."""
    return await copy_remote_dir_to_remote(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size
    )


async def remote_pull_file_execute(
    machine: str,
    remote_path: str,
    local_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyFileOutput:
    """Copy one file from a remote worker into the control server workspace."""
    return await copy_remote_file_to_local(
        machine, remote_path, local_path, overwrite, chunk_size
    )


async def remote_push_file_execute(
    local_path: str,
    machine: str,
    remote_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyFileOutput:
    """Copy one local workspace file to a remote worker."""
    return await copy_local_file_to_remote(
        local_path, machine, remote_path, overwrite, chunk_size
    )


async def remote_pull_dir_execute(
    machine: str,
    remote_path: str,
    local_path: str,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> RemoteCopyDirOutput:
    """Copy a directory tree from a remote worker into the control server workspace."""
    return await copy_remote_dir_to_local(
        machine, remote_path, local_path, overwrite, chunk_size
    )


async def remote_push_dir_execute(
    local_path: str,
    machine: str,
    remote_path: str,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> RemoteCopyDirOutput:
    """Copy a local workspace directory tree to a remote worker."""
    return await copy_local_dir_to_remote(
        local_path, machine, remote_path, overwrite, chunk_size
    )
