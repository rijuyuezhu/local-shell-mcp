"""Bash tool operations."""

import re
import shlex
from typing import Any

from ..schemas.result_models.bash import BashOutput
from ..tool_session.store import (
    get_tool_session_store,
    resolve_session_path,
)
from ..utils.serialization import to_jsonable
from .jobs import job_start_execute
from .shell import run_shell_command_execute, start_persistent_shell_execute
from .utils.remote_session import call_remote_session_tool

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _command_with_env(command: str, env: dict[str, str] | None) -> str:
    """Return a shell command prefixed with validated environment assignments."""
    if not env:
        return command
    assignments: list[str] = []
    for name, value in env.items():
        if not _ENV_NAME_RE.match(name):
            raise ValueError(f"Invalid environment variable name: {name!r}")
        assignments.append(f"{name}={shlex.quote(value)}")
    return f"{' '.join(assignments)} {command}"


def _as_result_dict(value: Any) -> dict[str, Any]:
    """Return a JSON-compatible result dictionary."""
    data = to_jsonable(value)
    return data if isinstance(data, dict) else {"result": data}


async def bash_execute(
    session_id: str,
    command: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
    env: dict[str, str] | None = None,
    async_: bool = False,
    pty: bool = False,
    name: str | None = None,
) -> BashOutput:
    """Run a shell command via bounded, tracked-job, or PTY mode."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "bash",
            {
                "command": command,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
                "env": env,
                "async_": async_,
                "pty": pty,
                "name": name,
            },
            timeout_s if isinstance(timeout_s, int) else None,
        )
        return BashOutput.model_validate(data)
    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    cwd_text = str(resolved_cwd)
    command_with_env = _command_with_env(command, env)
    if pty:
        result = await start_persistent_shell_execute(
            cwd_text, name, command_with_env
        )
        return BashOutput(
            mode="pty",
            command=command,
            cwd=cwd_text,
            result=_as_result_dict(result),
        )
    if async_:
        result = await job_start_execute(
            session_id, command_with_env, cwd_text, name
        )
        return BashOutput(
            mode="job",
            command=command,
            cwd=cwd_text,
            result=_as_result_dict(result),
        )
    result = await run_shell_command_execute(
        command_with_env, cwd_text, timeout_s, max_output_bytes
    )
    return BashOutput(
        mode="command",
        command=command,
        cwd=cwd_text,
        result=_as_result_dict(result),
    )
