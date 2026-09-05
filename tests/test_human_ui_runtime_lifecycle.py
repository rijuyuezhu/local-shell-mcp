import asyncio
from typing import Any

import pytest

from workgate.ui.http.live_state import (
    _RemoteFileSession,
    build_human_ui_runtime,
    human_ui_runtime,
)


async def _successful_worker_call(
    machine: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "machine": machine,
            "tool": tool,
            "session_id": args.get("session_id"),
            "timeout_s": timeout_s,
        },
    }


@pytest.mark.asyncio
async def test_human_ui_runtime_installs_and_restores_nested_bindings() -> None:
    outer = build_human_ui_runtime(_successful_worker_call)
    inner = build_human_ui_runtime(_successful_worker_call)

    await outer.start()
    try:
        assert human_ui_runtime() is outer
        await outer.start()

        await inner.start()
        try:
            assert human_ui_runtime() is inner
        finally:
            await inner.aclose()

        assert human_ui_runtime() is outer
        await inner.aclose()
    finally:
        await outer.aclose()

    with pytest.raises(RuntimeError, match="not configured"):
        human_ui_runtime()
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        await outer.start()


@pytest.mark.asyncio
async def test_terminal_connection_shutdown_cancels_owner_task() -> None:
    runtime = build_human_ui_runtime(_successful_worker_call)
    await runtime.start()
    entered = asyncio.Event()

    async def connection_owner() -> None:
        marker = runtime.terminal_connections.reserve(1)
        assert marker is not None
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            runtime.terminal_connections.release(marker)

    task = asyncio.create_task(connection_owner())
    await entered.wait()
    assert runtime.terminal_connections.active_count() == 1

    await runtime.aclose()

    assert task.cancelled()
    assert runtime.terminal_connections.active_count() == 0
    assert runtime.terminal_connections.reserve(1) is None
    await runtime.aclose()


@pytest.mark.asyncio
async def test_remote_file_shutdown_cancels_inflight_request() -> None:
    runtime = build_human_ui_runtime(_successful_worker_call)
    await runtime.start()
    entered = asyncio.Event()

    async def request_owner() -> None:
        operation = runtime.remote_files.begin_operation()
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            runtime.remote_files.end_operation(operation)

    task = asyncio.create_task(request_owner())
    await entered.wait()

    await runtime.aclose()

    assert task.cancelled()
    assert runtime.remote_files._operations == {}
    with pytest.raises(RuntimeError, match="closed"):
        runtime.remote_files.begin_operation()


@pytest.mark.asyncio
async def test_remote_file_shutdown_ends_owned_worker_sessions_once() -> None:
    calls: list[tuple[str, str, dict[str, Any], int | None]] = []

    async def call_worker(
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        calls.append((machine, tool, dict(args), timeout_s))
        return {"ok": True, "data": {"ended": True}}

    runtime = build_human_ui_runtime(call_worker)
    await runtime.start()
    runtime.remote_files.store(
        _RemoteFileSession("edge-a", "/work/a", "worker-session-a")
    )
    runtime.remote_files.store(
        _RemoteFileSession("edge-b", "/work/b", "worker-session-b")
    )
    runtime.remote_files.store(
        _RemoteFileSession("edge-a", "/work/a2", "worker-session-a2")
    )
    assert {
        session.worker_session_id for session in runtime.remote_files.snapshot()
    } == {
        "worker-session-a",
        "worker-session-a2",
        "worker-session-b",
    }

    await runtime.aclose()

    assert runtime.remote_files.snapshot() == ()
    assert {
        (machine, tool, args["session_id"])
        for machine, tool, args, _timeout in calls
    } == {
        ("edge-a", "session_end", "worker-session-a"),
        ("edge-a", "session_end", "worker-session-a2"),
        ("edge-b", "session_end", "worker-session-b"),
    }

    await runtime.aclose()
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_remote_file_cleanup_error_still_clears_owned_state() -> None:
    async def fail_worker_call(
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        return {"ok": False, "message": f"failed {tool} on {machine}"}

    runtime = build_human_ui_runtime(fail_worker_call)
    await runtime.start()
    runtime.remote_files.store(
        _RemoteFileSession("edge", "/work", "worker-session")
    )

    with pytest.raises(RuntimeError, match="failed to end 1"):
        await runtime.aclose()

    assert runtime.remote_files.snapshot() == ()
    with pytest.raises(RuntimeError, match="not configured"):
        human_ui_runtime()
    await runtime.aclose()


@pytest.mark.asyncio
async def test_human_ui_runtime_closes_terminal_connections_before_remote_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = build_human_ui_runtime(_successful_worker_call)
    await runtime.start()
    events: list[str] = []
    terminal_close = runtime.terminal_connections.aclose
    remote_files_close = runtime.remote_files.aclose

    async def close_terminals() -> None:
        events.append("terminals")
        await terminal_close()

    async def close_remote_files() -> None:
        events.append("remote-files")
        await remote_files_close()

    monkeypatch.setattr(runtime.terminal_connections, "aclose", close_terminals)
    monkeypatch.setattr(runtime.remote_files, "aclose", close_remote_files)

    await runtime.aclose()

    assert events == ["terminals", "remote-files"]
