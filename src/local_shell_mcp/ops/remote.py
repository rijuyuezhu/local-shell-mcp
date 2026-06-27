"""Remote worker operation helpers used by the remote tool registry."""

from typing import Any, cast

from ..remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ..schemas.result_models.remote import (
    RemoteAdminOutput,
    RemoteWorkerToolOutput,
)
from ..utils.serialization import to_jsonable


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
