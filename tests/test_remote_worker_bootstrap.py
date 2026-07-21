import asyncio
import builtins
import json
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
import asyncio
import builtins
import json

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


@pytest.mark.asyncio
async def test_worker_dispatches_persistent_shell_resize(monkeypatch):
    from local_shell_mcp.ops import shell as shell_ops
    from local_shell_mcp.remote_worker.dispatch import execute_worker_tool

    calls = []

    async def fake_resize(shell_id: str, cols: int, rows: int):
        calls.append((shell_id, cols, rows))
        return {
            "shell_id": shell_id,
            "cols": cols,
            "rows": rows,
            "resized": True,
            "backend": "tmux",
        }

    monkeypatch.setattr(
        shell_ops, "resize_persistent_shell_execute", fake_resize
    )

    result = await execute_worker_tool(
        "resize_persistent_shell",
        {"shell_id": "shell-1", "cols": 132, "rows": 38},
    )

    assert result["resized"] is True
    assert calls == [("shell-1", 132, 38)]


@pytest.mark.asyncio
async def test_worker_dispatches_persistent_shell_start(monkeypatch):
    from local_shell_mcp.ops import shell as shell_ops
    from local_shell_mcp.remote_worker.dispatch import execute_worker_tool

    calls = []

    async def fake_start(cwd: str, name: str | None, command: str | None):
        calls.append((cwd, name, command))
        return {
            "shell_id": "edge-shell",
            "name": name,
            "cwd": cwd,
            "command": command,
        }

    monkeypatch.setattr(shell_ops, "start_persistent_shell_execute", fake_start)

    result = await execute_worker_tool(
        "start_persistent_shell",
        {"cwd": "/edge", "name": "edge", "command": "bash"},
    )

    assert result["shell_id"] == "edge-shell"
    assert calls == [("/edge", "edge", "bash")]


def test_worker_session_start_result_serializes_with_dependency_shim(tmp_path):
    script = """
import asyncio
import json
import os

from local_shell_mcp.remote_worker.compat import install

install()

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.remote_worker import worker


async def main():
    workdir = os.environ["REMOTE_WORKDIR"]
    worker._configure_worker_runtime_env(workdir)
    clear_settings_cache()
    result = await worker.execute_worker_tool(
        "session_start",
        {"workdir": workdir, "target": "local", "machine": None, "label": None},
    )
    data = worker.to_jsonable(result)
    assert data["target"] == "local"
    assert data["workdir"] == workdir
    assert "model_fields" not in data
    assert data["git"]["is_repo"] is False
    assert "model_fields" not in data["git"]
    print(json.dumps(data, sort_keys=True))


asyncio.run(main())
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": "src",
            "REMOTE_WORKDIR": str(tmp_path),
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": "/workspace",
            "LOCAL_SHELL_MCP_STATE_DIR": "/workspace/.local-shell-mcp",
            "LOCAL_SHELL_MCP_WORKER_STATE_DIR": str(tmp_path / ".worker-state"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=".",
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert '"session_id"' in result.stdout


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


@pytest.mark.asyncio
async def test_worker_result_submission_keeps_heartbeats_while_retrying(
    monkeypatch,
):
    import local_shell_mcp.remote_worker.worker as worker

    result_attempts = 0
    heartbeat_calls = []
    result = {"job_id": "job-1", "ok": True, "data": {"done": True}}
    headers = {"Authorization": "Bearer token"}

    def fake_post(url, payload, request_headers=None, timeout=None):
        nonlocal result_attempts
        assert request_headers == headers
        assert timeout == 30
        if url.endswith("/result"):
            assert payload == result
            result_attempts += 1
            if result_attempts < 3:
                raise RuntimeError(
                    f"temporary result failure {result_attempts}"
                )
            return {"ok": True, "data": {"accepted": True}}
        assert url.endswith("/heartbeat")
        assert payload == {}
        heartbeat_calls.append(url)
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(worker, "_worker_post_json", fake_post)
    monkeypatch.setattr(worker, "_WORKER_RETRY_INITIAL_DELAY_S", 0.02)
    monkeypatch.setattr(worker, "_WORKER_RETRY_MAX_DELAY_S", 0.02)

    response = await worker._submit_worker_result_with_heartbeat(
        result,
        "https://example.test",
        headers,
        0.005,
    )

    assert response == {"ok": True, "data": {"accepted": True}}
    assert result_attempts == 3
    assert heartbeat_calls
    heartbeat_count = len(heartbeat_calls)
    await asyncio.sleep(0.02)
    assert len(heartbeat_calls) == heartbeat_count


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


def _configure_remote_state(tmp_path, monkeypatch, **overrides):
    from local_shell_mcp.config.settings import clear_settings_cache

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    for name, value in overrides.items():
        monkeypatch.setenv(f"LOCAL_SHELL_MCP_{name.upper()}", str(value))
    clear_settings_cache()


def test_worker_post_rejects_non_http_server_url(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setattr(worker.shutil, "which", lambda _name: None)

    with pytest.raises(ValueError, match="absolute HTTP"):
        worker._worker_post_json("file:///tmp/control", {})


@pytest.mark.asyncio
async def test_worker_post_forever_stops_on_permanent_http_error(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    calls = 0

    def reject(url, payload, headers=None, timeout=None):
        nonlocal calls
        calls += 1
        raise worker.WorkerHttpError(url, 400, "invalid registration")

    async def unexpected_sleep(_delay):
        raise AssertionError("permanent HTTP errors must not be retried")

    monkeypatch.setattr(worker, "_worker_post_json", reject)
    monkeypatch.setattr(worker.asyncio, "sleep", unexpected_sleep)

    with pytest.raises(worker.WorkerHttpError) as error:
        await worker._worker_post_json_forever(
            "https://example.test/remote/register", {}, operation="register"
        )

    assert error.value.status_code == 400
    assert calls == 1


@pytest.mark.asyncio
async def test_worker_post_forever_retries_transient_http_error(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    calls = 0
    sleeps = []

    def post(url, payload, headers=None, timeout=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise worker.WorkerHttpError(url, 503, "temporarily unavailable")
        return {"ok": True}

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(worker, "_worker_post_json", post)
    monkeypatch.setattr(worker.asyncio, "sleep", record_sleep)

    result = await worker._worker_post_json_forever(
        "https://example.test/remote/poll", {}, operation="poll"
    )

    assert result == {"ok": True}
    assert calls == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_long_worker_job_sends_heartbeats(monkeypatch):
    import local_shell_mcp.remote_worker.worker as worker

    heartbeat_urls = []

    async def slow_tool(tool, args):
        assert tool == "bash"
        assert args == {"command": "sleep"}
        await asyncio.sleep(0.04)
        return {"done": True}

    def post(url, payload, headers=None, timeout=None):
        heartbeat_urls.append(url)
        return {"ok": True}

    monkeypatch.setattr(worker, "execute_worker_tool", slow_tool)
    monkeypatch.setattr(worker, "_worker_post_json", post)

    result = await worker._execute_worker_job_with_heartbeat(
        {"tool": "bash", "args": {"command": "sleep"}},
        "https://example.test",
        {"Authorization": "Bearer token"},
        0.01,
    )

    assert result == {"done": True}
    assert heartbeat_urls
    assert set(heartbeat_urls) == {"https://example.test/remote/heartbeat"}


@pytest.mark.asyncio
async def test_remote_registry_recovers_from_backup(tmp_path, monkeypatch):
    from local_shell_mcp.remote.manager import RemoteManager

    _configure_remote_state(tmp_path, monkeypatch)
    manager = RemoteManager()
    invite = await manager.create_invite(name="backup-worker")
    registered = await manager.register_worker(
        {"invite": invite.code, "workdir": str(tmp_path)}
    )
    manager._registry_path().write_text("{broken", encoding="utf-8")

    recovered = RemoteManager()
    inventory = recovered.list_machines()

    assert inventory.counts == {"online": 0, "offline": 1, "total": 1}
    assert inventory.machines[0].name == "backup-worker"
    assert (
        json.loads(recovered._registry_path().read_text(encoding="utf-8"))[
            "workers"
        ][0]["access"]
        == registered["token"]
    )


def test_remote_registry_refuses_silent_reset_when_both_copies_are_corrupt(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote.manager import RemoteManager

    _configure_remote_state(tmp_path, monkeypatch)
    manager = RemoteManager()
    manager._registry_path().parent.mkdir(parents=True, exist_ok=True)
    manager._registry_path().write_text("{broken", encoding="utf-8")
    manager._registry_backup_path().write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to reset"):
        manager.list_machines()


@pytest.mark.asyncio
async def test_remote_queue_limit_counts_inflight_jobs(tmp_path, monkeypatch):
    from local_shell_mcp.remote.manager import RemoteManager, RemoteWorker, _utc

    _configure_remote_state(tmp_path, monkeypatch, remote_max_pending_jobs=1)
    manager = RemoteManager()
    manager._load_registry_unlocked()
    worker = RemoteWorker(name="worker", token="token", last_seen=_utc())
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    first = asyncio.create_task(
        manager.call("worker", "read", {"path": "a"}, timeout_s=10)
    )
    while worker.queue.qsize() == 0:
        await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="queue is full"):
        await manager.call("worker", "read", {"path": "b"}, timeout_s=10)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert manager.pending == {}
    assert manager.pending_machines == {}

    second = asyncio.create_task(
        manager.call("worker", "read", {"path": "c"}, timeout_s=10)
    )
    while not manager.pending:
        await asyncio.sleep(0)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second


@pytest.mark.asyncio
async def test_remote_poll_skips_cancelled_job_and_delivers_next(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote.manager import RemoteManager, RemoteWorker, _utc

    _configure_remote_state(tmp_path, monkeypatch)
    manager = RemoteManager()
    manager._load_registry_unlocked()
    worker = RemoteWorker(name="worker", token="token", last_seen=_utc())
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name
    manager.cancelled_jobs["cancelled"] = _utc()
    worker.queue.put_nowait({"id": "cancelled", "tool": "read", "args": {}})
    worker.queue.put_nowait({"id": "next", "tool": "read", "args": {}})

    result = await manager.poll("token")

    assert result["job"]["id"] == "next"
    assert "cancelled" not in manager.cancelled_jobs


@pytest.mark.asyncio
async def test_remote_result_is_rejected_from_wrong_worker(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote.manager import RemoteManager, RemoteWorker, _utc

    _configure_remote_state(tmp_path, monkeypatch)
    manager = RemoteManager()
    manager._load_registry_unlocked()
    worker_a = RemoteWorker(name="a", token="token-a", last_seen=_utc())
    worker_b = RemoteWorker(name="b", token="token-b", last_seen=_utc())
    manager.workers = {"a": worker_a, "b": worker_b}
    manager.tokens = {"token-a": "a", "token-b": "b"}
    future = asyncio.get_running_loop().create_future()
    manager.pending["job"] = future
    manager.pending_machines["job"] = "a"

    with pytest.raises(PermissionError, match="another worker"):
        await manager.submit_result(
            "token-b", {"job_id": "job", "ok": True, "data": {}}
        )

    assert not future.done()
    future.cancel()


def test_remote_machine_names_are_portably_validated(tmp_path, monkeypatch):
    from local_shell_mcp.remote.manager import RemoteManager

    _configure_remote_state(tmp_path, monkeypatch)
    manager = RemoteManager()

    with pytest.raises(ValueError, match="unsupported characters"):
        manager.rename("missing", "bad/name")
    with pytest.raises(ValueError, match="128 characters"):
        manager.rename("missing", "x" * 129)
