"""Session-aware shell and Python execution facade."""

import contextlib
from typing import Any

from ..jobs import runtime as jobs_runtime
from ..schemas.result_models.shell import (
    RunPythonCodeOutput,
    ShellExecutionOutput,
)
from ..tool_session.lifecycle import session_lifecycle_lock
from ..tool_session.store import get_tool_session_store, resolve_session_path
from ..utils.serialization import to_jsonable
from .shell import (
    _command_with_env,
    _effective_python_executable,
    _shell_join_argv,
    kill_persistent_shell_execute,
    run_shell_command_execute,
    start_persistent_shell_execute,
)
from .utils.remote_session import call_remote_session_tool
from .utils.temp_file import write_temp_text_file


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
) -> ShellExecutionOutput:
    """Run a shell command via bounded, tracked-job, or PTY mode inside a session."""
    if pty:
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
            if session.target == "remote":
                raise ValueError(
                    "PTY shell mode is not available for remote sessions; "
                    "use bounded commands or async jobs instead"
                )
            resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
            cwd_text = str(resolved_cwd)
            command_with_env = _command_with_env(command, env)
            result = await start_persistent_shell_execute(
                cwd_text,
                name,
                command_with_env,
                owner_session_id=session_id,
            )
            try:
                get_tool_session_store().register_persistent_shell(
                    session_id, result.shell_id
                )
            except BaseException:
                with contextlib.suppress(Exception):
                    await kill_persistent_shell_execute(result.shell_id)
                raise
            return ShellExecutionOutput(
                mode="pty",
                command=command,
                cwd=cwd_text,
                result=_as_result_dict(result),
            )

    if not async_:
        async with session_lifecycle_lock(session_id):
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
                        "async_": False,
                        "pty": False,
                        "name": name,
                    },
                    timeout_s if isinstance(timeout_s, int) else None,
                )
                return ShellExecutionOutput.model_validate(data)
            resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
            cwd_text = str(resolved_cwd)
            result = await run_shell_command_execute(
                command, cwd_text, timeout_s, max_output_bytes, env
            )
            return ShellExecutionOutput(
                mode="command",
                command=command,
                cwd=cwd_text,
                result=_as_result_dict(result),
            )

    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
            data = await call_remote_session_tool(
                session,
                "bash",
                {
                    "command": command,
                    "cwd": cwd,
                    "timeout_s": timeout_s,
                    "max_output_bytes": max_output_bytes,
                    "env": env,
                    "async_": True,
                    "pty": False,
                    "name": name,
                },
                timeout_s if isinstance(timeout_s, int) else None,
            )
            return ShellExecutionOutput.model_validate(data)

    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    cwd_text = str(resolved_cwd)
    command_with_env = _command_with_env(command, env)
    result = await jobs_runtime.job_start_execute(
        session_id, command_with_env, cwd_text, name
    )
    return ShellExecutionOutput(
        mode="job",
        command=command,
        cwd=cwd_text,
        result=_as_result_dict(result),
    )


async def run_python_code_execute(
    session_id: str,
    code: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
    env: dict[str, str] | None = None,
    async_: bool = False,
    pty: bool = False,
    name: str | None = None,
) -> RunPythonCodeOutput:
    """Write Python code to a temporary file and execute it through shell modes."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
            data = await call_remote_session_tool(
                session,
                "run_python_code",
                {
                    "code": code,
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
            return RunPythonCodeOutput.model_validate(data)

    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    script_path = await write_temp_text_file(
        "Python script", code, "script", "py"
    )
    command = _shell_join_argv(
        [_effective_python_executable(), str(script_path)]
    )
    result = await bash_execute(
        session_id,
        command,
        str(resolved_cwd),
        timeout_s,
        max_output_bytes,
        env,
        async_,
        pty,
        name,
    )
    return RunPythonCodeOutput(
        **result.model_dump(), script_path=str(script_path)
    )
