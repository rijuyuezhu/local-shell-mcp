import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import local_shell_mcp.executors.http.tool_routes as http_tool_routes_module
import local_shell_mcp.ops.shell as shell_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.executors.http.app import build_http_app
from local_shell_mcp.executors.mcp.app import build_mcp
from local_shell_mcp.ops.shell import (
    SHELL_TIMEOUT_CLEANUP_GRACE_S,
    _shared_tail_bytes,
    _shell_command_args,
    _subprocess_env,
    _tmux_session_name,
    check_command_policy,
    clamp_timeout,
    read_persistent_shell_output_execute,
    resize_persistent_shell_execute,
    run_shell,
    run_shell_command_timeout,
    send_persistent_shell_input_execute,
    tool_timeout_s,
)
from local_shell_mcp.schemas.result_models.shell import CommandResult
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.registry import files as fs_tools_module
from tests.helpers import (
    mcp_structured,
)
from tests.helpers import (
    python_shell_command as _python_shell_command,
)


def test_shell_command_args_are_native_for_supported_shells():
    assert _shell_command_args("/bin/bash", "echo hi") == [
        "/bin/bash",
        "-lc",
        "echo hi",
    ]
    assert _shell_command_args("cmd.exe", "echo hi") == [
        "cmd.exe",
        "/D",
        "/S",
        "/C",
        "echo hi",
    ]
    assert _shell_command_args("pwsh.exe", "Write-Output hi") == [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Write-Output hi",
    ]


def test_command_with_env_uses_powershell_assignments(monkeypatch):
    monkeypatch.setattr(
        shell_ops, "_effective_shell_executable", lambda: "pwsh.exe"
    )

    command = shell_ops._command_with_env(
        "Write-Output ok", {"TOKEN": "O'Reilly"}
    )

    assert command == "$env:TOKEN='O''Reilly'; Write-Output ok"


def test_command_with_env_uses_cmd_assignments(monkeypatch):
    monkeypatch.setattr(
        shell_ops, "_effective_shell_executable", lambda: "cmd.exe"
    )

    command = shell_ops._command_with_env("echo ok", {"TOKEN": "a b"})

    assert command == 'set "TOKEN=a b" && echo ok'


def test_command_denylist_matching_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_COMMAND_DENYLIST", "RM -RF")
    clear_settings_cache()

    with pytest.raises(PermissionError, match="denylisted fragment"):
        check_command_policy("rm -rf /tmp/example")


def test_tmux_session_name_strips_invalid_edges_and_has_safe_fallback():
    assert _tmux_session_name("  ..example shell--  ") == "example-shell"

    fallback = _tmux_session_name("..--")
    assert fallback.startswith("mcp-")
    assert len(fallback) <= 64


@pytest.mark.asyncio
async def test_bash_rejects_timeout_above_public_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    mcp = build_mcp()
    session = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )

    with pytest.raises(ToolError, match="timeout_s must be <= 120 seconds"):
        await mcp.call_tool(
            "bash",
            {
                "session_id": session["session_id"],
                "command": "echo ok",
                "timeout_s": 3600,
            },
        )


def test_shell_tool_watchdog_reserves_cleanup_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S", "1")
    clear_settings_cache()

    assert SHELL_TIMEOUT_CLEANUP_GRACE_S == 10
    assert tool_timeout_s("list_files") == 0.01
    assert tool_timeout_s("bash") == 11
    assert tool_timeout_s("run_python_code") == 11


@pytest.mark.asyncio
async def test_mcp_shell_timeout_returns_partial_output_after_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    mcp = build_mcp()
    session = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S", "1")
    clear_settings_cache()
    command = _python_shell_command(
        'import sys, time; print("partial-out", flush=True); '
        'print("partial-err", file=sys.stderr, flush=True); time.sleep(5)'
    )

    payload = mcp_structured(
        await mcp.call_tool(
            "bash",
            {
                "session_id": session["session_id"],
                "command": command,
                "timeout_s": 1,
            },
        )
    )
    result = payload["result"]

    assert payload["mode"] == "command"
    assert result["timed_out"] is True
    assert "partial-out" in result["stdout"]
    assert "partial-err" in result["stderr"]


def test_rest_shell_timeout_returns_partial_output_after_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S", "1")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session_id = get_tool_session_store().create_session(workdir=".").session_id
    command = _python_shell_command(
        'import sys, time; print("partial-out", flush=True); '
        'print("partial-err", file=sys.stderr, flush=True); time.sleep(5)'
    )
    response = client.post(
        "/tools/bash",
        json={
            "session_id": session_id,
            "command": command,
            "timeout_s": 1,
        },
    )
    result = response.json()["result"]

    assert response.status_code == 200
    assert result["timed_out"] is True
    assert "partial-out" in result["stdout"]
    assert "partial-err" in result["stderr"]


def test_rest_tool_watchdog_returns_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def hanging_call_local_tool(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        http_tool_routes_module, "call_http_tool", hanging_call_local_tool
    )

    response = TestClient(build_http_app()).post(
        "/tools/list_files", json={"path": "."}
    )

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


def test_rest_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()

    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def blocking_list_dir(*args, **kwargs):
        await asyncio.sleep(0.2)
        return []

    monkeypatch.setattr(
        fs_tools_module, "list_files_dispatch_execute", blocking_list_dir
    )
    response = client.post(
        "/tools/list_files",
        json={"session_id": session["session_id"], "path": "."},
    )

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


def test_rest_tool_watchdog_preserves_file_and_todo_mutations(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def delayed_call_http_tool(tool_name, args):
        await asyncio.sleep(0.05)
        return {"tool": tool_name}

    monkeypatch.setattr(
        http_tool_routes_module, "call_http_tool", delayed_call_http_tool
    )
    client = TestClient(build_http_app())

    write_response = client.post("/tools/write_file", json={})
    todo_write_response = client.post("/tools/todo", json={})
    todo_read_response = client.get("/tools/todo")

    assert write_response.status_code == 200
    assert write_response.json() == {"tool": "write_file"}
    assert todo_write_response.status_code == 200
    assert todo_write_response.json() == {"tool": "write_todos"}
    assert todo_read_response.status_code == 504
    assert todo_read_response.json()["error"] == "tool_timeout"


def test_rest_readyz_does_not_expose_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    clear_settings_cache()

    response = TestClient(build_http_app()).get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    mcp = build_mcp()
    session = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )

    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def blocking_list_dir(*args, **kwargs):
        await asyncio.sleep(0.2)
        return []

    monkeypatch.setattr(
        fs_tools_module, "list_files_dispatch_execute", blocking_list_dir
    )
    with pytest.raises(
        ToolError, match="list_files exceeded 0.01 second tool timeout"
    ):
        await mcp.call_tool(
            "list_files", {"session_id": session["session_id"], "path": "."}
        )


def test_apply_patch_watchdog_covers_both_git_phases(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "15")
    clear_settings_cache()

    assert tool_timeout_s("apply_patch") == 45
    assert tool_timeout_s("list_files") == 15


def test_run_shell_command_timeout_uses_ten_second_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S", "10")
    clear_settings_cache()

    assert run_shell_command_timeout(None) == 10


@pytest.mark.asyncio
async def test_spawn_process_uses_native_shell_api_for_cmd(monkeypatch):
    calls = []
    sentinel = object()

    async def fake_shell(command: str, **kwargs):
        calls.append((command, kwargs))
        return sentinel

    async def unexpected_exec(*args, **kwargs):
        raise AssertionError("cmd.exe must use create_subprocess_shell")

    monkeypatch.setattr(
        shell_ops, "_effective_shell_executable", lambda: "cmd.exe"
    )
    monkeypatch.setattr(shell_ops, "_subprocess_env", lambda: {"BASE": "1"})
    monkeypatch.setattr(
        shell_ops.asyncio, "create_subprocess_shell", fake_shell
    )
    monkeypatch.setattr(
        shell_ops.asyncio, "create_subprocess_exec", unexpected_exec
    )

    result = await shell_ops._spawn_process("echo hi", ".", {"EXTRA": "2"})

    assert result is sentinel
    assert calls[0][0] == "echo hi"
    assert calls[0][1]["executable"] == "cmd.exe"
    assert calls[0][1]["env"] == {"BASE": "1", "EXTRA": "2"}


def test_run_shell_command_timeout_allows_explicit_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    assert run_shell_command_timeout(120) == 120


def test_internal_shell_timeout_uses_at_least_builtin_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S", "5")
    clear_settings_cache()

    assert clamp_timeout(None) == 60


def test_internal_shell_timeout_uses_larger_run_shell_values(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S", "120")
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S", "7200")
    clear_settings_cache()

    assert clamp_timeout(None) == 120
    assert clamp_timeout(9999) == 7200


@pytest.mark.asyncio
async def test_run_shell_command_timeout_includes_subprocess_spawn(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    async def hanging_spawn(
        command: str, cwd: str, env: dict[str, str] | None = None
    ):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell._spawn_process", hanging_spawn
    )

    result = await run_shell("echo never", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


@pytest.mark.asyncio
async def test_run_shell_command_fast_command_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell("echo ok", timeout_s=5)

    assert result.ok is True
    assert result.timed_out is False
    assert "ok" in result.stdout


@pytest.mark.asyncio
async def test_run_shell_command_streams_and_bounds_large_output(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell(
        _python_shell_command('import sys; sys.stdout.write("x" * 200000)'),
        timeout_s=5,
        max_output_bytes=1000,
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.stdout.encode()) == 1000
    assert result.stderr == ""


def test_shared_tail_bytes_uses_idle_stream_capacity_and_preserves_tails():
    stdout, stderr, truncated = _shared_tail_bytes(
        b"prefix-" + b"o" * 900,
        b"e" * 300,
        1000,
    )

    assert truncated is True
    assert len(stdout) == 700
    assert len(stderr) == 300
    assert stdout == b"o" * 700
    assert stderr == b"e" * 300


def test_shared_tail_bytes_gives_remaining_capacity_to_stderr():
    stdout, stderr, truncated = _shared_tail_bytes(
        b"o" * 300,
        b"prefix-" + b"e" * 900,
        1000,
    )

    assert truncated is True
    assert stdout == b"o" * 300
    assert stderr == b"e" * 700


def test_tail_buffer_ignores_empty_chunks():
    tail = shell_ops.TailBuffer(keep_bytes=4, data=bytearray(b"ok"))

    tail.append(b"")

    assert tail.data == bytearray(b"ok")
    assert tail.total_bytes == 0


@pytest.mark.asyncio
async def test_run_shell_uses_unused_stderr_budget_for_stdout(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell(
        _python_shell_command('import sys; sys.stdout.write("x" * 1500)'),
        timeout_s=5,
        max_output_bytes=2000,
    )

    assert result.ok is True
    assert result.truncated is False
    assert len(result.stdout.encode()) == 1500
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_run_shell_shares_total_budget_between_streams(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell(
        _python_shell_command(
            'import sys; sys.stdout.write("o" * 900); '
            'sys.stderr.write("e" * 900)'
        ),
        timeout_s=5,
        max_output_bytes=1000,
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.stdout.encode()) == 500
    assert len(result.stderr.encode()) == 500
    assert len(result.stdout.encode()) + len(result.stderr.encode()) == 1000


@pytest.mark.asyncio
async def test_run_shell_command_timeout_marks_result_and_cleans_up(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell("sleep 30", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True


@pytest.mark.skipif(os.name == "nt", reason="tmux-specific behavior")
@pytest.mark.asyncio
async def test_read_persistent_shell_preserves_ansi_only_when_requested(
    monkeypatch,
):
    calls = []

    async def fake_tmux(args: list[str], timeout_s: int = 10):
        calls.append((args, timeout_s))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command="tmux",
            stdout="\x1b[32mready\x1b[0m",
        )

    monkeypatch.setattr("local_shell_mcp.ops.shell.tmux", fake_tmux)

    plain = await read_persistent_shell_output_execute("shell-1", 40)
    colored = await read_persistent_shell_output_execute(
        "shell-1", 40, preserve_ansi=True
    )

    assert plain.output == "\x1b[32mready\x1b[0m"
    assert colored.output == plain.output
    assert calls == [
        (["capture-pane", "-p", "-t", "shell-1", "-S", "-40"], 10),
        (["capture-pane", "-p", "-e", "-t", "shell-1", "-S", "-40"], 10),
    ]


@pytest.mark.skipif(os.name == "nt", reason="tmux-specific behavior")
@pytest.mark.asyncio
async def test_resize_persistent_shell_resizes_tmux_window(monkeypatch):
    calls = []

    async def fake_tmux(args: list[str], timeout_s: int = 10):
        calls.append((args, timeout_s))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command="tmux",
        )

    monkeypatch.setattr("local_shell_mcp.ops.shell.tmux", fake_tmux)

    result = await resize_persistent_shell_execute("shell-1", 180, 42)

    assert result.model_dump() == {
        "shell_id": "shell-1",
        "cols": 180,
        "rows": 42,
        "resized": True,
        "backend": "tmux",
    }
    assert calls == [
        (["resize-window", "-t", "shell-1", "-x", "180", "-y", "42"], 10)
    ]


@pytest.mark.asyncio
async def test_resize_persistent_shell_rejects_invalid_dimensions():
    with pytest.raises(ValueError, match="cols must be between"):
        await resize_persistent_shell_execute("shell-1", 10, 24)
    with pytest.raises(ValueError, match="rows must be between"):
        await resize_persistent_shell_execute("shell-1", 80, 2)


@pytest.mark.skipif(os.name == "nt", reason="tmux-specific behavior")
@pytest.mark.asyncio
async def test_send_shell_invokes_tmux_promptly(monkeypatch):
    calls = []

    async def fake_tmux(args: list[str], timeout_s: int = 10):
        calls.append((args, timeout_s))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command="tmux",
        )

    monkeypatch.setattr("local_shell_mcp.ops.shell.tmux", fake_tmux)

    result = await asyncio.wait_for(
        send_persistent_shell_input_execute("shell-1", "echo ok", enter=True),
        timeout=1,
    )

    assert result.model_dump() == {
        "shell_id": "shell-1",
        "sent_bytes": 7,
        "enter": True,
    }
    assert calls == [
        (["send-keys", "-l", "-t", "shell-1", "echo ok"], 10),
        (["send-keys", "-t", "shell-1", "Enter"], 10),
    ]


@pytest.mark.asyncio
async def test_run_shell_command_filters_server_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "should-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/app/src")
    monkeypatch.setenv("DOCKER_RUN_AS_ROOT", "false")
    monkeypatch.setenv("DOCKER_PERSISTENT_CREDENTIALS", "true")
    monkeypatch.setenv("DOCKER_CREDENTIALS_DIR", "/persist/credentials")
    monkeypatch.setenv("DOCKER_CHOWN_WORKSPACE", "true")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", "should-not-leak")
    clear_settings_cache()

    result = await run_shell(
        _python_shell_command(
            "import os; "
            "blocked = ('PYTHONPATH', 'CLOUDFLARE_TUNNEL_TOKEN'); "
            "keys = [key for key in sorted(os.environ) "
            "if key in blocked or key.startswith('LOCAL_SHELL_MCP_') "
            "or key.startswith('DOCKER_')]; "
            "print('\\n'.join(f'{key}={os.environ[key]}' for key in keys), end='')"
        ),
        cwd=str(tmp_path),
    )

    assert result.ok
    assert result.stdout == ""


def test_frozen_subprocess_env_restores_loader_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/bundled")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/bundled/libpreload.so")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/tmp/bundled")
    monkeypatch.setenv("DYLD_LIBRARY_PATH_ORIG", "/opt/homebrew/lib")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/tmp/bundled/libinject.dylib")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/bundled", raising=False)
    clear_settings_cache()

    env = _subprocess_env()

    assert env["LD_LIBRARY_PATH"] == "/usr/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env
    assert "LD_PRELOAD" not in env
    assert env["DYLD_LIBRARY_PATH"] == "/opt/homebrew/lib"
    assert "DYLD_LIBRARY_PATH_ORIG" not in env
    assert "DYLD_INSERT_LIBRARIES" not in env


def test_non_frozen_subprocess_env_preserves_loader_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/custom/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/original/lib")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    clear_settings_cache()

    env = _subprocess_env()

    assert env["LD_LIBRARY_PATH"] == "/custom/lib"
    assert env["LD_LIBRARY_PATH_ORIG"] == "/original/lib"
