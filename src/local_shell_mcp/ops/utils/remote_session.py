"""Session-bound remote worker dispatch helpers."""

from typing import Any, cast

from ...remote.service import call_remote_worker_tool
from ...tool_session.store import AgentSession


def _remote_binding(session: AgentSession) -> tuple[str, str]:
    """Return the machine and worker session id for a remote session."""
    if session.target != "remote":
        raise ValueError("session is not remote")
    if not session.machine:
        raise RuntimeError("remote session is missing machine")
    if not session.worker_session_id:
        raise RuntimeError("remote session is missing worker_session_id")
    return session.machine, session.worker_session_id


def _remote_result_data(
    result: dict[str, Any], *, tool: str, machine: str
) -> dict[str, Any]:
    """Extract successful worker data or raise a clear remote dispatch error."""
    if not result.get("ok", False):
        message = str(
            result.get("message") or f"remote {tool} failed on {machine}"
        )
        raise RuntimeError(message)
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        message = str(
            data.get("message") or f"remote {tool} failed on {machine}"
        )
        error_type = str(data.get("error_type") or "remote_error")
        raise RuntimeError(f"{error_type}: {message}")
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return {"result": data}


def _rewrite_worker_session_ids(
    value: Any, *, worker_session_id: str, control_session_id: str
) -> Any:
    """Rewrite worker-side session_id fields to the control-server session_id."""
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "session_id" and item == worker_session_id:
                rewritten[key] = control_session_id
            else:
                rewritten[key] = _rewrite_worker_session_ids(
                    item,
                    worker_session_id=worker_session_id,
                    control_session_id=control_session_id,
                )
        return rewritten
    if isinstance(value, list):
        return [
            _rewrite_worker_session_ids(
                item,
                worker_session_id=worker_session_id,
                control_session_id=control_session_id,
            )
            for item in value
        ]
    return value


async def call_remote_session_tool(
    session: AgentSession,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call a worker-side tool for a control-server remote session."""
    machine, worker_session_id = _remote_binding(session)
    payload = {**args, "session_id": worker_session_id}
    result = await call_remote_worker_tool(machine, tool, payload, timeout_s)
    data = _remote_result_data(result, tool=tool, machine=machine)
    return cast(
        dict[str, Any],
        _rewrite_worker_session_ids(
            data,
            worker_session_id=worker_session_id,
            control_session_id=session.session_id,
        ),
    )


async def start_worker_session(
    *,
    machine: str,
    workdir: str,
    label: str | None = None,
) -> dict[str, Any]:
    """Create a local agent session on a remote worker."""
    payload: dict[str, Any] = {"target": "local", "workdir": workdir}
    if label is not None:
        payload["label"] = label
    result = await call_remote_worker_tool(machine, "session_start", payload)
    return _remote_result_data(result, tool="session_start", machine=machine)
