from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import local_shell_mcp.conpty as conpty
import local_shell_mcp.ops.shell as shell_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.errors import (
    PathNotFoundError,
    ShellExecutableNotFoundError,
    exception_from_tool_error,
    process_start_not_found_error,
    tool_error_payload,
    workspace_path_not_found_error,
)
from local_shell_mcp.ops.session import session_start_execute
from local_shell_mcp.ops.utils.path import resolve_path
from local_shell_mcp.ops.utils.remote_session import _remote_result_data
from local_shell_mcp.remote.bundle import worker_bundle_bytes
from local_shell_mcp.remote.manager import RemoteManager, RemoteWorker, _utc
from local_shell_mcp.remote_worker.worker import _handled_remote_exception
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tool_session.store import get_tool_session_store


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    clear_settings_cache()
    get_tool_session_store().clear()


def test_process_start_classifies_missing_cwd_before_executable(
    tmp_path: Path,
) -> None:
    missing_cwd = tmp_path / "vanished"
    exc = FileNotFoundError(2, "No such file or directory", "/bin/sh")

    result = process_start_not_found_error(
        exc,
        executable="/bin/sh",
        command="echo ok",
        cwd=missing_cwd,
    )

    assert isinstance(result, PathNotFoundError)
    assert result.path == missing_cwd


def test_workspace_path_detection_uses_missing_second_endpoint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("data", encoding="utf-8")
    missing_destination = tmp_path / "removed-parent" / "destination.txt"
    exc = FileNotFoundError(2, "No such file or directory", str(source))
    exc.filename2 = str(missing_destination)

    result = workspace_path_not_found_error(exc, tmp_path)

    assert isinstance(result, PathNotFoundError)
    assert result.path == missing_destination


def test_workspace_path_detection_ignores_untrusted_endpoints(
    tmp_path: Path,
) -> None:
    relative = FileNotFoundError(2, "missing", "relative.txt")
    outside = FileNotFoundError(
        2, "missing", str(tmp_path.parent / "outside-workspace")
    )

    assert workspace_path_not_found_error(relative, tmp_path) is None
    assert workspace_path_not_found_error(outside, tmp_path) is None


def test_resolve_path_raises_explicit_path_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)

    with pytest.raises(PathNotFoundError) as raised:
        resolve_path("missing.txt", must_exist=True)

    assert raised.value.path == tmp_path / "missing.txt"


@pytest.mark.asyncio
async def test_bounded_shell_reports_missing_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    executable = "local-shell-mcp-missing-shell-issue-106"
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
    clear_settings_cache()

    with pytest.raises(ShellExecutableNotFoundError) as raised:
        await shell_ops._spawn_process("echo ok", str(tmp_path))

    assert raised.value.executable == executable
    assert raised.value.command == "echo ok"
    assert raised.value.cwd == str(tmp_path)


@pytest.mark.asyncio
async def test_bounded_shell_reports_vanished_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_cwd = tmp_path / "vanished"

    async def fail_spawn(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise FileNotFoundError(2, "No such file or directory", "/bin/sh")

    monkeypatch.setattr(
        shell_ops, "_effective_shell_executable", lambda: "/bin/sh"
    )
    monkeypatch.setattr(shell_ops.asyncio, "create_subprocess_exec", fail_spawn)

    with pytest.raises(PathNotFoundError) as raised:
        await shell_ops._spawn_process("echo ok", str(missing_cwd))

    assert raised.value.path == missing_cwd


@pytest.mark.asyncio
async def test_conpty_reports_missing_shell_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    executable = "missing-conpty-shell"
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
    clear_settings_cache()
    monkeypatch.setattr(conpty, "is_available", lambda: True)

    def fail_spawn(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise FileNotFoundError(2, "missing", executable)

    monkeypatch.setattr(conpty, "_spawn_pty", fail_spawn)

    with pytest.raises(ShellExecutableNotFoundError) as raised:
        await conpty.start_shell(
            shell_id="missing-conpty",
            cwd=tmp_path,
            command=None,
        )

    assert raised.value.executable == executable
    assert raised.value.command == executable


def test_worker_error_payload_round_trips_typed_failures(
    tmp_path: Path,
) -> None:
    shell_error = ShellExecutableNotFoundError(
        "missing-shell", "echo ok", tmp_path, "[WinError 2]"
    )
    encoded = tool_error_payload(shell_error, workspace_root=tmp_path)

    assert encoded["status"] == "executable_not_found"
    reconstructed = exception_from_tool_error(encoded)
    assert isinstance(reconstructed, ShellExecutableNotFoundError)
    assert reconstructed.executable == "missing-shell"
    assert reconstructed.command == "echo ok"

    path_error = PathNotFoundError(tmp_path / "missing.txt")
    encoded_path = tool_error_payload(path_error, workspace_root=tmp_path)
    reconstructed_path = exception_from_tool_error(encoded_path)
    assert isinstance(reconstructed_path, PathNotFoundError)
    assert reconstructed_path.path == tmp_path / "missing.txt"


@pytest.mark.asyncio
async def test_posix_persistent_shell_preflights_default_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    executable = "missing-tmux-shell"
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
    clear_settings_cache()
    monkeypatch.setattr(
        shell_ops, "_use_conpty_persistent_shell_backend", lambda: False
    )
    monkeypatch.setattr(shell_ops.shutil, "which", lambda *args, **kwargs: None)

    with pytest.raises(ShellExecutableNotFoundError) as raised:
        await shell_ops.start_persistent_shell_execute(cwd=str(tmp_path))

    assert raised.value.executable == executable
    assert raised.value.cwd == str(tmp_path)


@pytest.mark.asyncio
async def test_manager_preserves_structured_worker_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    clear_settings_cache()
    manager = RemoteManager()
    manager._load_registry_unlocked()
    worker = RemoteWorker(name="worker", token="token", last_seen=_utc())
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    call = asyncio.create_task(
        manager.call("worker", "bash", {"command": "echo ok"}, timeout_s=10)
    )
    while worker.queue.qsize() == 0:
        await asyncio.sleep(0)
    job = worker.queue.get_nowait()
    data = {
        "status": "executable_not_found",
        "error_type": "FileNotFoundError",
        "message": "Shell executable not found: missing-shell",
        "executable": "missing-shell",
        "command": "echo ok",
        "cwd": str(tmp_path),
        "original_error": "[WinError 2]",
    }

    accepted = await manager.submit_result(
        "token",
        {
            "job_id": job["id"],
            "ok": False,
            "error": "FileNotFoundError",
            "message": data["message"],
            "data": data,
        },
    )
    result = await call

    assert accepted == {"accepted": True}
    assert result == {"ok": True, "message": "", "data": data}


def test_worker_serializer_and_controller_facade_preserve_error_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    exc = ShellExecutableNotFoundError(
        "missing-shell", "echo ok", tmp_path, "[WinError 2]"
    )

    result = _handled_remote_exception(exc)

    assert result["ok"] is False
    assert result["data"]["status"] == "executable_not_found"
    with pytest.raises(ShellExecutableNotFoundError):
        _remote_result_data(
            {"ok": True, "data": result["data"]},
            tool="bash",
            machine="worker-a",
        )


def test_source_only_bundle_contains_shared_error_module() -> None:
    with tarfile.open(
        fileobj=io.BytesIO(worker_bundle_bytes()), mode="r:gz"
    ) as archive:
        names = set(archive.getnames())

    assert "local_shell_mcp/errors.py" in names


def test_http_shell_error_is_not_misreported_as_workspace_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    executable = "missing-http-shell"
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    response = client.post(
        "/tools/bash",
        json={
            "session_id": session["session_id"],
            "command": "echo ok",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "FileNotFoundError"
    assert response.json()["message"] == (
        f"FileNotFoundError: Shell executable not found: {executable}"
    )
    assert str(tmp_path) not in response.json()["message"]


@pytest.mark.asyncio
async def test_mcp_shell_error_uses_standard_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(tmp_path, monkeypatch)
    executable = "missing-mcp-shell"
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_EXECUTABLE", executable)
    clear_settings_cache()
    session = await session_start_execute(".", "local", None, None)

    with pytest.raises(
        ToolError, match=f"Shell executable not found: {executable}"
    ):
        await build_mcp().call_tool(
            "bash",
            {"session_id": session.session_id, "command": "echo ok"},
        )
