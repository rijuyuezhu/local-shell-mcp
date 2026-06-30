import builtins
import os
import subprocess
import sys
import urllib.error
import urllib.request
from email.message import Message
from io import BytesIO

import pytest


def test_remote_worker_entrypoint_import_is_dependency_light():
    script = """
import builtins

blocked = {"fastapi", "httpx", "mcp", "starlette", "uvicorn", "pydantic", "pydantic_settings", "yaml", "pathspec"}
real_import = builtins.__import__


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] in blocked:
        raise AssertionError(f"unexpected bootstrap import: {name}")
    return real_import(name, globals, locals, fromlist, level)


builtins.__import__ = guarded_import
import local_shell_mcp.remote_worker
from local_shell_mcp.remote_worker.worker import worker_capabilities, worker_info

assert "shell" in worker_capabilities()
assert worker_info(".")["workdir"] == "."
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=".",
        env={"PYTHONPATH": "src"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_execute_worker_tool_imports_registry_lazily(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    real_import = builtins.__import__
    seen_mcp_import = False

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        nonlocal seen_mcp_import
        if name.split(".")[0] == "mcp":
            seen_mcp_import = True
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert "shell" in worker.worker_capabilities()
    assert seen_mcp_import is False


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.body


def test_worker_post_json_posts_json_and_returns_object(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setattr(worker.shutil, "which", lambda name: None)
    captured: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["content_type"] = request.get_header("Content-type")
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _FakeResponse(b'{"ok": true, "data": {"value": 1}}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = worker._worker_post_json(
        "https://example.test/remote/register",
        {"invite": "abc"},
        headers={"Authorization": "Bearer token"},
        timeout=30,
    )

    assert result == {"ok": True, "data": {"value": 1}}
    assert captured == {
        "url": "https://example.test/remote/register",
        "data": b'{"invite": "abc"}',
        "content_type": "application/json",
        "authorization": "Bearer token",
        "timeout": 30,
    }


def test_worker_post_json_rejects_non_object_response(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setattr(worker.shutil, "which", lambda name: None)

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        return _FakeResponse(b'["not", "an", "object"]')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(
        RuntimeError, match="returned JSON list, expected object"
    ):
        worker._worker_post_json("https://example.test/remote/poll", {})


def test_worker_post_json_includes_http_error_detail(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setattr(worker.shutil, "which", lambda name: None)

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=Message(),
            fp=BytesIO(b'{"message": "bad invite"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        worker._worker_post_json("https://example.test/remote/register", {})

    assert "failed with 400" in str(exc_info.value)
    assert "bad invite" in str(exc_info.value)


def test_worker_post_json_wraps_url_errors(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setattr(worker.shutil, "which", lambda name: None)

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(
        RuntimeError, match="worker HTTP request failed: connection refused"
    ):
        worker._worker_post_json("https://example.test/remote/poll", {})


def test_worker_post_json_uses_curl_when_available(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    captured: dict[str, object] = {}

    def fake_run(command, *, input, capture_output, check):
        captured["command"] = command
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["check"] = check
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b'{"ok": true}\nLOCAL_SHELL_MCP_HTTP_STATUS:200',
            stderr=b"",
        )

    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    result = worker._worker_post_json(
        "https://example.test/remote/poll",
        {},
        headers={"X-Test": "value"},
        timeout=12,
    )

    assert result == {"ok": True}
    assert captured["input"] == b"{}"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:3] == ["/usr/bin/curl", "--max-time", "12"]
    assert "X-Test: value" in command


def test_worker_retry_delay_is_capped():
    import local_shell_mcp.remote_worker.worker as worker

    assert [worker._worker_retry_delay(i) for i in range(7)] == [
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
    ]


@pytest.mark.asyncio
async def test_worker_post_json_forever_retries_until_success(
    monkeypatch, capsys
):
    import local_shell_mcp.remote_worker.worker as worker

    calls = []
    sleeps = []

    def fake_post(url, payload, headers=None, timeout=None):
        calls.append((url, payload, headers, timeout))
        if len(calls) < 3:
            raise RuntimeError(f"temporary failure {len(calls)}")
        return {"ok": True, "data": {"heartbeat": True}}

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(worker, "_worker_post_json", fake_post)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    result = await worker._worker_post_json_forever(
        "https://example.test/remote/poll",
        {},
        {"X-Test": "value"},
        12,
        "poll",
    )

    assert result == {"ok": True, "data": {"heartbeat": True}}
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
    assert (
        "Status: poll failed: temporary failure 1. Retrying in 1s..."
        in capsys.readouterr().err
    )


def test_worker_runtime_env_replaces_default_workspace_paths(
    tmp_path, monkeypatch
):
    import local_shell_mcp.remote_worker.worker as worker

    workdir = tmp_path / "remote-workdir"
    worker_state = tmp_path / "worker-state"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "/workspace")
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_STATE_DIR", "/workspace/.local-shell-mcp"
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(worker_state))

    worker._configure_worker_runtime_env(str(workdir))

    assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == str(workdir)
    assert os.environ["LOCAL_SHELL_MCP_STATE_DIR"] == str(
        worker_state / "runtime"
    )
    assert os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL"] == "true"


def test_worker_runtime_env_preserves_explicit_custom_paths(
    tmp_path, monkeypatch
):
    import local_shell_mcp.remote_worker.worker as worker

    custom_workspace = tmp_path / "custom-workspace"
    custom_state = tmp_path / "custom-state"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(custom_workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(custom_state))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "false")

    worker._configure_worker_runtime_env(str(tmp_path / "remote-workdir"))

    assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == str(custom_workspace)
    assert os.environ["LOCAL_SHELL_MCP_STATE_DIR"] == str(custom_state)
    assert os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL"] == "true"


def test_worker_identity_round_trips_and_filters_by_server_name(
    tmp_path, monkeypatch
):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))

    worker._write_worker_identity(
        {
            "server": "https://example.test",
            "name": "machine-a",
            "access": "worker-access",
        }
    )

    assert worker._read_worker_identity(
        "https://example.test", "machine-a"
    ) == {
        "server": "https://example.test",
        "name": "machine-a",
        "access": "worker-access",
    }
    assert (
        worker._read_worker_identity("https://other.test", "machine-a") is None
    )
    assert (
        worker._read_worker_identity("https://example.test", "machine-b")
        is None
    )


def test_worker_cli_keyboard_interrupt_exits_cleanly():
    code = """
from argparse import Namespace
from local_shell_mcp.remote_worker import worker


def fake_asyncio_run(coro):
    coro.close()
    raise KeyboardInterrupt


worker.asyncio.run = fake_asyncio_run
worker.run_worker_from_args(
    Namespace(
        server="https://example.test",
        invite="lsmcp_inv_test",
        name=None,
        workdir=None,
        persist=False,
    )
)
"""

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=".",
        env={"PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 130
    assert "Status: disconnected by user." in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.asyncio
async def test_remote_manager_persists_workers_and_resumes(
    tmp_path, monkeypatch
):
    from local_shell_mcp.config.settings import clear_settings_cache
    from local_shell_mcp.remote.manager import RemoteManager

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()

    manager = RemoteManager()
    invite = await manager.create_invite(name="worker-a")
    registered = await manager.register_worker(
        {
            "invite": invite.code,
            "workdir": str(tmp_path),
            "capabilities": ["shell"],
            "info": {"hostname": "remote-host"},
        }
    )

    reloaded = RemoteManager()
    inventory = reloaded.list_machines()
    assert inventory.counts == {"online": 0, "offline": 1, "total": 1}
    assert inventory.machines[0].name == "worker-a"
    assert inventory.machines[0].queue_depth == 0

    resumed = await reloaded.resume_worker(
        registered["token"],
        {"name": "worker-a", "workdir": str(tmp_path / "remote")},
    )
    assert resumed["name"] == "worker-a"
    assert resumed["token"] == registered["token"]
    assert reloaded.list_machines().counts == {
        "online": 1,
        "offline": 0,
        "total": 1,
    }


@pytest.mark.asyncio
async def test_remote_manager_list_machines_reports_counts_and_details(
    tmp_path, monkeypatch
):
    from local_shell_mcp.config.settings import clear_settings_cache
    from local_shell_mcp.remote.manager import RemoteManager, RemoteWorker

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()

    manager = RemoteManager()
    manager._load_registry_unlocked()
    now = 1_000_000.0
    monkeypatch.setattr("local_shell_mcp.remote.manager._utc", lambda: now)

    recent = RemoteWorker(
        name="recent-worker", token="recent", last_seen=now - 5
    )
    stale = RemoteWorker(
        name="stale-worker", token="stale", last_seen=now - 500
    )
    manager.workers = {recent.name: recent, stale.name: stale}
    manager.tokens = {recent.token: recent.name, stale.token: stale.name}
    recent.queue.put_nowait({"id": "job-1"})

    result = manager.list_machines()

    assert result.counts == {"online": 1, "offline": 1, "total": 2}
    assert [machine.name for machine in result.machines] == [
        "recent-worker",
        "stale-worker",
    ]
    assert result.machines[0].last_seen_age_s == 5
    assert result.machines[0].queue_depth == 1
    assert result.machines[0].offline_after_s == 60
