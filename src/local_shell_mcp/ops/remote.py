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
    RemoteFacadeOutput,
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
    """Return a JSON-compatible dict payload for facade outputs."""
    data = to_jsonable(value)
    return (
        cast(dict[str, Any], data)
        if isinstance(data, dict)
        else {"result": data}
    )


def _required_str(args: dict[str, Any], name: str) -> str:
    """Extract a required string argument from a facade args dict."""
    value = args.get(name)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"Missing required argument for remote facade: {name}")
    return value


def _optional_int(args: dict[str, Any], name: str) -> int | None:
    """Extract an optional integer facade argument."""
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"Remote facade argument {name!r} must be an integer")
    return value


def _optional_bool(args: dict[str, Any], name: str, *, default: bool) -> bool:
    """Extract an optional boolean facade argument."""
    value = args.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"Remote facade argument {name!r} must be a boolean")
    return value


async def remote_admin_execute(
    action: str, args: dict[str, Any]
) -> RemoteAdminOutput:
    """Run one remote control-plane action through a compact facade."""
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


REMOTE_SESSION_ACTION_TOOL_MAP: dict[str, str] = {
    "send": "send_persistent_shell_input",
    "read": "read_persistent_shell_output",
    "kill": "kill_persistent_shell",
    "list": "list_persistent_shells",
}
"""Map remote session companion actions to worker tool names."""


REMOTE_FACADE_TOOL_MAP: dict[str, str] = {
    "environment": "environment_info",
    "read": "read",
    "search": "search",
    "edit_lines": "edit_lines",
    "bash": "bash",
    "python": "run_python_code",
    "list_files": "list_files",
    "tree": "tree_view",
    "glob": "glob_search",
    "write_file": "write_file",
    "apply_patch": "apply_patch",
    "delete": "delete_file_or_dir",
    "job": "job",
}
"""Map high-level remote facade operations to worker tool names."""


def _remote_facade_timeout(op: str, args: dict[str, Any]) -> int | None:
    """Return the worker-call timeout to use for a facade operation."""
    timeout = args.get("timeout_s")
    if isinstance(timeout, int):
        return timeout
    if op == "python":
        return 60
    return None


async def _remote_session_execute(
    machine: str, args: dict[str, Any]
) -> RemoteFacadeOutput:
    """Run a persistent-shell companion action through remote()."""
    action = _required_str(args, "action")
    try:
        tool = REMOTE_SESSION_ACTION_TOOL_MAP[action]
    except KeyError as exc:
        supported = ", ".join(sorted(REMOTE_SESSION_ACTION_TOOL_MAP))
        raise ValueError(
            f"Unsupported remote session action {action!r}; supported: {supported}"
        ) from exc
    result = await remote_worker_tool_execute(
        {**args, "machine": machine}, tool
    )
    return RemoteFacadeOutput(
        machine=machine, op="session", tool=tool, data=_json_dict(result)
    )


async def _remote_transfer_execute(
    machine: str, args: dict[str, Any]
) -> RemoteFacadeOutput:
    """Run a high-level transfer action through remote()."""
    action = _required_str(args, "action")
    chunk_size = _optional_int(args, "chunk_size")
    if action == "pull_file":
        result = await remote_pull_file_execute(
            machine,
            _required_str(args, "remote_path"),
            _required_str(args, "local_path"),
            _optional_bool(args, "overwrite", default=True),
            chunk_size,
        )
    elif action == "push_file":
        result = await remote_push_file_execute(
            _required_str(args, "local_path"),
            machine,
            _required_str(args, "remote_path"),
            _optional_bool(args, "overwrite", default=True),
            chunk_size,
        )
    elif action == "pull_dir":
        result = await remote_pull_dir_execute(
            machine,
            _required_str(args, "remote_path"),
            _required_str(args, "local_path"),
            _optional_bool(args, "overwrite", default=False),
            chunk_size,
        )
    elif action == "push_dir":
        result = await remote_push_dir_execute(
            _required_str(args, "local_path"),
            machine,
            _required_str(args, "remote_path"),
            _optional_bool(args, "overwrite", default=False),
            chunk_size,
        )
    elif action == "copy_file":
        result = await remote_copy_file_execute(
            str(args.get("src_machine") or machine),
            _required_str(args, "src_path"),
            _required_str(args, "dst_machine"),
            _required_str(args, "dst_path"),
            _optional_bool(args, "overwrite", default=True),
            chunk_size,
        )
    elif action == "copy_dir":
        result = await remote_copy_dir_execute(
            str(args.get("src_machine") or machine),
            _required_str(args, "src_path"),
            _required_str(args, "dst_machine"),
            _required_str(args, "dst_path"),
            _optional_bool(args, "overwrite", default=False),
            chunk_size,
        )
    else:
        raise ValueError(
            "Unsupported remote transfer action "
            f"{action!r}; supported: copy_dir, copy_file, pull_dir, "
            "pull_file, push_dir, push_file"
        )
    return RemoteFacadeOutput(
        machine=machine,
        op="transfer",
        tool=f"remote_transfer:{action}",
        data=_json_dict(result),
    )


async def remote_execute(
    machine: str, op: str, args: dict[str, Any]
) -> RemoteFacadeOutput:
    """Run one high-level operation on a remote worker."""
    if op == "session":
        return await _remote_session_execute(machine, args)
    if op == "transfer":
        return await _remote_transfer_execute(machine, args)
    try:
        tool = REMOTE_FACADE_TOOL_MAP[op]
    except KeyError as exc:
        supported = ", ".join(
            sorted((*REMOTE_FACADE_TOOL_MAP, "session", "transfer"))
        )
        raise ValueError(
            f"Unsupported remote op {op!r}; supported: {supported}"
        ) from exc
    payload = {**args, "machine": machine}
    result = await remote_worker_tool_execute(
        payload, tool, _remote_facade_timeout(op, args)
    )
    return RemoteFacadeOutput(
        machine=machine, op=op, tool=tool, data=_json_dict(result)
    )


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
