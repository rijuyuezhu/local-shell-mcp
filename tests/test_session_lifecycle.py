import asyncio
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.tool_session import lifecycle
from local_shell_mcp.tool_session.store import (
    SESSION_ACTIVE_WINDOW_S,
    ExpiredAgentSessionError,
    UnknownAgentSessionError,
    get_tool_session_store,
)
from local_shell_mcp.utils.private_files import private_file_lock


def _start_cross_process_lifecycle_holder(
    session_ids: tuple[str, ...], marker: Path, release: Path
) -> subprocess.Popen[str]:
    script = f"""
import asyncio
from pathlib import Path
from local_shell_mcp.tool_session.lifecycle import session_lifecycle_locks

async def main():
    async with session_lifecycle_locks({session_ids!r}):
        Path({str(marker)!r}).write_text("locked", encoding="utf-8")
        while not Path({str(release)!r}).exists():
            await asyncio.sleep(0.01)

asyncio.run(main())
"""
    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


async def _wait_for_process_marker(
    process: subprocess.Popen[str], marker: Path
) -> None:
    for _ in range(500):
        if marker.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"lifecycle holder exited early\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        await asyncio.sleep(0.01)
    raise AssertionError("lifecycle holder did not acquire its leases")


@pytest.mark.asyncio
async def test_session_lifecycle_lock_serializes_and_releases_entry():
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            second_entered.set()

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0)
    assert not second_entered.is_set()

    release_first.set()
    await first_task
    await second_task

    assert second_entered.is_set()
    assert "SESSION1" not in lifecycle._ENTRIES


@pytest.mark.asyncio
async def test_cancelled_lifecycle_waiter_does_not_leak_entry():
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            holder_entered.set()
            await release_holder.wait()

    async def waiter() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            raise AssertionError("cancelled waiter must not enter")

    holder_task = asyncio.create_task(holder())
    await holder_entered.wait()
    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    release_holder.set()
    await holder_task

    assert "SESSION1" not in lifecycle._ENTRIES


@pytest.mark.asyncio
async def test_reset_lifecycle_locks_rejects_active_entries():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()

    with pytest.raises(RuntimeError, match="while in use"):
        lifecycle.reset_session_lifecycle_locks_for_tests()

    release.set()
    await task
    lifecycle.reset_session_lifecycle_locks_for_tests()
    assert lifecycle._ENTRIES == {}


@pytest.mark.asyncio
async def test_multiple_lifecycle_locks_are_sorted_and_deduplicated():
    async with lifecycle.session_lifecycle_locks(
        ("SESSION2", "SESSION1", "SESSION2")
    ):
        assert set(lifecycle._ENTRIES) == {"SESSION1", "SESSION2"}
        assert all(entry.lock.locked() for entry in lifecycle._ENTRIES.values())

    assert lifecycle._ENTRIES == {}


@pytest.mark.asyncio
async def test_session_lifecycle_lock_serializes_across_processes(tmp_path):
    marker = tmp_path / "child-acquired"
    release = tmp_path / "release-child"
    script = f"""
import asyncio
from pathlib import Path
from local_shell_mcp.tool_session.lifecycle import session_lifecycle_lock

async def main():
    async with session_lifecycle_lock("SESSION1"):
        Path({str(marker)!r}).write_text("locked", encoding="utf-8")
        while not Path({str(release)!r}).exists():
            await asyncio.sleep(0.01)

asyncio.run(main())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    contender_entered = asyncio.Event()

    async def contender() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            contender_entered.set()

    try:
        for _ in range(500):
            if marker.exists():
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"child exited before acquiring lock\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )
            await asyncio.sleep(0.01)
        assert marker.exists()

        task = asyncio.create_task(contender())
        await asyncio.sleep(0.1)
        assert not contender_entered.is_set()

        release.write_text("release", encoding="utf-8")
        await asyncio.wait_for(contender_entered.wait(), timeout=5)
        await task
        assert await asyncio.to_thread(process.wait, timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_cancelled_cross_process_waiter_releases_local_entry():
    external_acquired = threading.Event()
    release_external = threading.Event()
    path = lifecycle._lifecycle_lock_path("SESSION1")

    def hold_external_lock() -> None:
        with private_file_lock(path):
            external_acquired.set()
            release_external.wait()

    holder = threading.Thread(target=hold_external_lock, daemon=True)
    holder.start()
    assert await asyncio.to_thread(external_acquired.wait, 2)

    async def waiter() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            raise AssertionError("cancelled waiter must not enter")

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert "SESSION1" not in lifecycle._ENTRIES
    release_external.set()
    await asyncio.to_thread(holder.join, 2)
    assert not holder.is_alive()


@pytest.mark.asyncio
async def test_job_admission_revalidates_after_cross_process_teardown(
    tmp_path, monkeypatch
):
    from local_shell_mcp.jobs import runtime as jobs_ops

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=".")
    marker = tmp_path / "teardown-complete"
    release = tmp_path / "release-teardown"
    script = f"""
import asyncio
from pathlib import Path
from local_shell_mcp.tool_session.lifecycle import session_lifecycle_lock
from local_shell_mcp.tool_session.store import get_tool_session_store

async def main():
    async with session_lifecycle_lock({session.session_id!r}):
        get_tool_session_store().end_session({session.session_id!r})
        Path({str(marker)!r}).write_text("deleted", encoding="utf-8")
        while not Path({str(release)!r}).exists():
            await asyncio.sleep(0.01)

asyncio.run(main())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(500):
            if marker.exists():
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"teardown child exited early\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )
            await asyncio.sleep(0.01)
        assert marker.exists()

        admission = asyncio.create_task(
            jobs_ops.job_start_execute(session.session_id, "echo too-late")
        )
        await asyncio.sleep(0.1)
        assert not admission.done()

        release.write_text("release", encoding="utf-8")
        with pytest.raises(UnknownAgentSessionError):
            await asyncio.wait_for(admission, timeout=5)
        assert await asyncio.to_thread(process.wait, timeout=5) == 0
        assert jobs_ops._load_store()["jobs"] == []
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_try_lifecycle_lease_skips_local_users_and_lock_uncertainty(
    monkeypatch,
):
    with lifecycle.try_session_lifecycle_lease("SESSION1") as acquired:
        assert acquired is True

    async with lifecycle.session_lifecycle_lock("SESSION1"):
        with lifecycle.try_session_lifecycle_lease("SESSION1") as acquired:
            assert acquired is False

    def fail_lock(*_args, **_kwargs):
        raise OSError("lock state unavailable")

    monkeypatch.setattr(lifecycle, "private_file_lock", fail_lock)
    with lifecycle.try_session_lifecycle_lease("SESSION1") as acquired:
        assert acquired is False


@pytest.mark.asyncio
async def test_expiry_pruning_skips_cross_process_foreground_lease(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        workdir=tmp_path,
        expires_at=time.time() - 1,
    )
    marker = tmp_path / "foreground-lease-held"
    release = tmp_path / "release-foreground-lease"
    process = _start_cross_process_lifecycle_holder(
        (session.session_id,), marker, release
    )

    try:
        await _wait_for_process_marker(process, marker)

        listed_ids = {item.session_id for item in store.list_sessions()}
        assert session.session_id in listed_ids

        release.write_text("release", encoding="utf-8")
        assert await asyncio.to_thread(process.wait, timeout=5) == 0

        listed_ids = {item.session_id for item in store.list_sessions()}
        assert session.session_id not in listed_ids
    finally:
        release.touch(exist_ok=True)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        clear_settings_cache()


@pytest.mark.asyncio
async def test_overflow_pruning_skips_cross_process_copy_endpoint_leases(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "86400")
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    source = store.create_session(workdir=tmp_path)
    destination = store.create_session(workdir=tmp_path)
    stale_updated_at = time.time() - SESSION_ACTIVE_WINDOW_S - 60
    for session in (source, destination):
        stale = replace(session, updated_at=stale_updated_at)
        store._state_store.write_json(
            store._metadata_path(session.session_id), asdict(stale)
        )

    marker = tmp_path / "copy-leases-held"
    release = tmp_path / "release-copy-leases"
    process = _start_cross_process_lifecycle_holder(
        (source.session_id, destination.session_id), marker, release
    )

    try:
        await _wait_for_process_marker(process, marker)
        monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
        clear_settings_cache()

        listed_ids = {item.session_id for item in store.list_sessions()}
        assert listed_ids == {source.session_id, destination.session_id}

        release.write_text("release", encoding="utf-8")
        assert await asyncio.to_thread(process.wait, timeout=5) == 0

        assert len(store.list_sessions()) == 1
    finally:
        release.touch(exist_ok=True)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        clear_settings_cache()


@pytest.mark.asyncio
async def test_required_expiry_preserves_local_lifecycle_holder(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        workdir=tmp_path,
        expires_at=time.time() - 1,
    )
    metadata_path = store._metadata_path(session.session_id)

    async with lifecycle.session_lifecycle_lock(session.session_id):
        with pytest.raises(ExpiredAgentSessionError):
            store.require_session(session.session_id)
        assert metadata_path.exists()

    with pytest.raises(ExpiredAgentSessionError):
        store.require_session(session.session_id)
    assert not metadata_path.exists()


@pytest.mark.asyncio
async def test_required_expiry_preserves_cross_process_lifecycle_holder(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        workdir=tmp_path,
        expires_at=time.time() - 1,
    )
    metadata_path = store._metadata_path(session.session_id)
    marker = tmp_path / "required-expiry-lease-held"
    release = tmp_path / "release-required-expiry-lease"
    process = _start_cross_process_lifecycle_holder(
        (session.session_id,), marker, release
    )

    try:
        await _wait_for_process_marker(process, marker)

        with pytest.raises(ExpiredAgentSessionError):
            store.require_session(session.session_id)
        assert metadata_path.exists()

        release.write_text("release", encoding="utf-8")
        assert await asyncio.to_thread(process.wait, timeout=5) == 0

        with pytest.raises(ExpiredAgentSessionError):
            store.require_session(session.session_id)
        assert not metadata_path.exists()
    finally:
        release.touch(exist_ok=True)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        clear_settings_cache()
