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
    RemoteAdminOutput,
    RemoteCopyDirOutput,
    RemoteCopyFileOutput,
    RemoteInviteOutput,
    RemoteListMachinesOutput,
    RemoteRenameMachineOutput,
    RemoteRevokeMachineOutput,
    RemoteWorkerToolOutput,
)
from ..utils.serialization import to_jsonable


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
    return {
        key: value
        for key, value in args.items()
        if key not in {"machine", "action"}
    }


def _json_dict(value: Any) -> dict[str, Any]:
    """Return a JSON-compatible dict payload for remote outputs."""
    data = to_jsonable(value)
    return (
        cast(dict[str, Any], data)
        if isinstance(data, dict)
        else {"result": data}
    )


def _required_str(args: dict[str, Any], name: str) -> str:
    """Extract a required string argument from a remote args dict."""
    value = args.get(name)
    if not isinstance(value, str) or value == "":
        raise ValueError(
            f"Missing required argument for remote operation: {name}"
        )
    return value


def _optional_int(args: dict[str, Any], name: str) -> int | None:
    """Extract an optional integer remote argument."""
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"Remote argument {name!r} must be an integer")
    return value


def _optional_bool(args: dict[str, Any], name: str, *, default: bool) -> bool:
    """Extract an optional boolean remote argument."""
    value = args.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"Remote argument {name!r} must be a boolean")
    return value


async def remote_admin_execute(
    action: str, args: dict[str, Any]
) -> RemoteAdminOutput:
    """Run one remote control-plane action."""
    if action == "invite":
        result = await create_remote_invite(
            args.get("name"), args.get("workdir"), args.get("ttl_s")
        )
    elif action == "list":
        result = list_remote_machines()
    elif action == "revoke":
        result = revoke_remote_machine(_required_str(args, "machine"))
    elif action == "rename":
        result = rename_remote_machine(
            _required_str(args, "machine"), _required_str(args, "new_name")
        )
    else:
        raise ValueError(
            "Unsupported remote admin action "
            f"{action!r}; supported: invite, list, revoke, rename"
        )
    return RemoteAdminOutput(action=action, data=_json_dict(result))


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
        return RemoteWorkerToolOutput(**_json_dict(data))
    return RemoteWorkerToolOutput(**result)


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
