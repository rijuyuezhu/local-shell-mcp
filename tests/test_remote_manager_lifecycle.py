import asyncio

import pytest

from local_shell_mcp.config.settings import Settings
from local_shell_mcp.persistence import FileStateStore
from local_shell_mcp.remote.bundle import worker_bundle_manifest
from local_shell_mcp.remote.manager import (
    RemoteManager,
    RemoteManagerClosedError,
    RemoteWorker,
    _utc,
)


def _manager(tmp_path) -> tuple[Settings, RemoteManager]:
    settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / ".state",
        remote_poll_timeout_s=30,
        remote_job_timeout_s=30,
    )
    state_store = FileStateStore(lambda: settings.state_dir)
    return settings, RemoteManager(lambda: settings, state_store=state_store)


def _poll_report() -> dict[str, object]:
    manifest = worker_bundle_manifest()
    return {
        "protocol_version": 2,
        "runtime_kind": "managed_bundle",
        "worker_version": str(manifest["bundle_version"]),
        "bundle_version": str(manifest["bundle_version"]),
        "bundle_sha256": str(manifest["sha256"]),
        "poll_timeout_s": 30,
    }


@pytest.mark.asyncio
async def test_remote_manager_close_stops_pending_calls_and_admission(tmp_path):
    _settings, manager = _manager(tmp_path)
    await manager.start()
    worker = RemoteWorker(name="worker", token="token", last_seen=_utc())
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    call_task = asyncio.create_task(
        manager.call("worker", "read", {"path": "demo.txt"}, timeout_s=30)
    )
    while not manager.pending:
        await asyncio.sleep(0)

    assert worker.queue.qsize() == 1
    await manager.aclose()

    with pytest.raises(RemoteManagerClosedError, match="closed"):
        await call_task
    assert manager.pending == {}
    assert manager.pending_machines == {}
    assert worker.queue.empty()

    await manager.aclose()
    with pytest.raises(RemoteManagerClosedError, match="closed"):
        await manager.call("worker", "read", {}, timeout_s=1)
    with pytest.raises(RemoteManagerClosedError, match="closed"):
        manager.rename("worker", "renamed")


@pytest.mark.asyncio
async def test_remote_manager_close_cancels_owned_poll_waiters(tmp_path):
    _settings, manager = _manager(tmp_path)
    await manager.start()
    worker = RemoteWorker(name="worker", token="token", last_seen=_utc())
    manager.workers[worker.name] = worker
    manager.tokens[worker.token] = worker.name

    poll_task = asyncio.create_task(manager.poll("token", _poll_report()))
    while not manager._poll_waiters:
        await asyncio.sleep(0)

    await manager.aclose()

    with pytest.raises(RemoteManagerClosedError, match="closed"):
        await poll_task
    assert manager._poll_waiters == set()
