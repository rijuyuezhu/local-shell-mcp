from typing import Any

import pytest

import local_shell_mcp.ops.utils.remote_session as remote_session_utils
import local_shell_mcp.ops.utils.session_copy as session_copy_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops.session import session_copy_execute
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.local_handlers import (
    call_local_tool,
    local_tool_handlers,
)
from local_shell_mcp.utils.serialization import to_jsonable


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    local_tool_handlers.cache_clear()
    store = get_tool_session_store()
    store.clear()
    return tmp_path, store


async def _fake_remote_call(
    machine: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> dict[str, Any]:
    _ = (machine, timeout_s)
    try:
        return {
            "ok": True,
            "data": to_jsonable(await call_local_tool(tool, args)),
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _install_fake_remote(monkeypatch):
    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_call(
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        calls.append((machine, tool, dict(args)))
        return await _fake_remote_call(machine, tool, args, timeout_s)

    monkeypatch.setattr(session_copy_ops, "call_remote_worker_tool", fake_call)
    monkeypatch.setattr(
        remote_session_utils, "call_remote_worker_tool", fake_call
    )
    return calls


@pytest.mark.asyncio
async def test_session_copy_local_file_streams_between_session_workdirs(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "dst").mkdir()
    payload = b"abcdef" * 1000
    (root / "src" / "payload.bin").write_bytes(payload)
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    result = await session_copy_execute(
        src.session_id,
        "payload.bin",
        dst.session_id,
        "copied.bin",
        chunk_size=128,
    )

    assert result.kind == "file"
    assert result.relation.route == "local_to_local"
    assert result.relation.same_target is True
    assert result.relation.same_session is False
    assert result.bytes == len(payload)
    assert result.chunks > 1
    assert result.source.session_id == src.session_id
    assert result.destination.session_id == dst.session_id
    assert (root / "dst" / "copied.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_session_copy_local_directory_packs_unpacks_and_cleans_temp(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src" / "tree" / "nested").mkdir(parents=True)
    (root / "dst").mkdir()
    (root / "src" / "tree" / "nested" / "note.txt").write_text(
        "hello", encoding="utf-8"
    )
    (root / "src" / "tree" / "data.bin").write_bytes(b"\x00\x01")
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    result = await session_copy_execute(
        src.session_id,
        "tree",
        dst.session_id,
        "tree-copy",
        kind="dir",
        chunk_size=256,
    )

    assert result.kind == "dir"
    assert result.relation.route == "local_to_local"
    assert result.entries is not None and result.entries >= 2
    assert result.archive_bytes is not None and result.archive_bytes > 0
    assert (root / "dst" / "tree-copy" / "nested" / "note.txt").read_text(
        encoding="utf-8"
    ) == "hello"
    assert (root / "dst" / "tree-copy" / "data.bin").read_bytes() == b"\x00\x01"
    tmp_files = list((root / ".local-shell-mcp" / "tmp").glob("*"))
    assert tmp_files == []


@pytest.mark.asyncio
async def test_session_copy_rejects_source_path_escape(tmp_path, monkeypatch):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "dst").mkdir()
    (root / "escape.txt").write_text("secret", encoding="utf-8")
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    with pytest.raises(ValueError, match="Path escapes session workdir"):
        await session_copy_execute(
            src.session_id, "../escape.txt", dst.session_id, "escape.txt"
        )

    assert not (root / "dst" / "escape.txt").exists()


@pytest.mark.asyncio
async def test_session_copy_respects_overwrite_false(tmp_path, monkeypatch):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "dst").mkdir()
    (root / "src" / "payload.txt").write_text("new", encoding="utf-8")
    (root / "dst" / "payload.txt").write_text("old", encoding="utf-8")
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    with pytest.raises(FileExistsError):
        await session_copy_execute(
            src.session_id,
            "payload.txt",
            dst.session_id,
            "payload.txt",
            overwrite=False,
        )

    assert (root / "dst" / "payload.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_session_copy_rejects_kind_mismatch(tmp_path, monkeypatch):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "dst").mkdir()
    (root / "src" / "payload.txt").write_text("file", encoding="utf-8")
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    with pytest.raises(ValueError, match="not requested kind dir"):
        await session_copy_execute(
            src.session_id,
            "payload.txt",
            dst.session_id,
            "payload-copy",
            kind="dir",
        )


@pytest.mark.asyncio
async def test_session_copy_local_to_remote_file_uses_worker_session(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    calls = _install_fake_remote(monkeypatch)
    (root / "src").mkdir()
    (root / "worker").mkdir()
    (root / "src" / "payload.bin").write_bytes(b"remote" * 500)
    src = store.create_session(workdir="src")
    worker = store.create_session(workdir="worker")
    remote = store.create_session(
        target="remote",
        workdir="/remote/workdir",
        machine="worker-a",
        worker_session_id=worker.session_id,
    )

    result = await session_copy_execute(
        src.session_id,
        "payload.bin",
        remote.session_id,
        "copied.bin",
        chunk_size=64,
    )

    assert result.relation.route == "local_to_remote"
    assert result.destination.target == "remote"
    assert result.destination.machine == "worker-a"
    assert (root / "worker" / "copied.bin").read_bytes() == b"remote" * 500
    assert any(
        tool == "transfer_begin_write"
        and args.get("session_id") == worker.session_id
        for _, tool, args in calls
    )


@pytest.mark.asyncio
async def test_session_copy_remote_to_local_file_uses_worker_session(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    calls = _install_fake_remote(monkeypatch)
    (root / "worker").mkdir()
    (root / "dst").mkdir()
    (root / "worker" / "payload.bin").write_bytes(b"from-remote" * 400)
    worker = store.create_session(workdir="worker")
    remote = store.create_session(
        target="remote",
        workdir="/remote/workdir",
        machine="worker-a",
        worker_session_id=worker.session_id,
    )
    dst = store.create_session(workdir="dst")

    result = await session_copy_execute(
        remote.session_id,
        "payload.bin",
        dst.session_id,
        "copied.bin",
        chunk_size=128,
    )

    assert result.relation.route == "remote_to_local"
    assert result.source.target == "remote"
    assert (root / "dst" / "copied.bin").read_bytes() == b"from-remote" * 400
    assert any(
        tool == "transfer_read_chunk"
        and args.get("session_id") == worker.session_id
        for _, tool, args in calls
    )


@pytest.mark.asyncio
async def test_session_copy_remote_to_remote_different_machines_file(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    _install_fake_remote(monkeypatch)
    (root / "worker-a").mkdir()
    (root / "worker-b").mkdir()
    (root / "worker-a" / "payload.bin").write_bytes(b"rr" * 1000)
    worker_a = store.create_session(workdir="worker-a")
    worker_b = store.create_session(workdir="worker-b")
    remote_a = store.create_session(
        target="remote",
        workdir="/remote/a",
        machine="worker-a",
        worker_session_id=worker_a.session_id,
    )
    remote_b = store.create_session(
        target="remote",
        workdir="/remote/b",
        machine="worker-b",
        worker_session_id=worker_b.session_id,
    )

    result = await session_copy_execute(
        remote_a.session_id,
        "payload.bin",
        remote_b.session_id,
        "copied.bin",
        chunk_size=32,
    )

    assert result.relation.route == "remote_to_remote_different_machines"
    assert result.relation.same_machine is False
    assert result.chunks > 1
    assert (root / "worker-b" / "copied.bin").read_bytes() == b"rr" * 1000


@pytest.mark.asyncio
async def test_session_copy_remote_to_remote_same_machine_reports_relation(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    _install_fake_remote(monkeypatch)
    (root / "worker" / "src").mkdir(parents=True)
    (root / "worker" / "dst").mkdir()
    (root / "worker" / "src" / "payload.txt").write_text(
        "same-machine", encoding="utf-8"
    )
    worker_src = store.create_session(workdir="worker/src")
    worker_dst = store.create_session(workdir="worker/dst")
    remote_src = store.create_session(
        target="remote",
        workdir="/remote/src",
        machine="worker-a",
        worker_session_id=worker_src.session_id,
    )
    remote_dst = store.create_session(
        target="remote",
        workdir="/remote/dst",
        machine="worker-a",
        worker_session_id=worker_dst.session_id,
    )

    result = await session_copy_execute(
        remote_src.session_id,
        "payload.txt",
        remote_dst.session_id,
        "payload.txt",
    )

    assert result.relation.route == "remote_to_remote_same_machine"
    assert result.relation.same_machine is True
    assert (root / "worker" / "dst" / "payload.txt").read_text(
        encoding="utf-8"
    ) == "same-machine"


@pytest.mark.asyncio
async def test_session_copy_remote_directory_to_local(tmp_path, monkeypatch):
    root, store = _workspace(tmp_path, monkeypatch)
    _install_fake_remote(monkeypatch)
    (root / "worker" / "tree" / "nested").mkdir(parents=True)
    (root / "dst").mkdir()
    (root / "worker" / "tree" / "nested" / "note.txt").write_text(
        "remote-dir", encoding="utf-8"
    )
    worker = store.create_session(workdir="worker")
    remote = store.create_session(
        target="remote",
        workdir="/remote/workdir",
        machine="worker-a",
        worker_session_id=worker.session_id,
    )
    dst = store.create_session(workdir="dst")

    result = await session_copy_execute(
        remote.session_id,
        "tree",
        dst.session_id,
        "tree-copy",
        kind="dir",
        chunk_size=128,
    )

    assert result.kind == "dir"
    assert result.relation.route == "remote_to_local"
    assert result.entries is not None and result.entries >= 1
    assert (root / "dst" / "tree-copy" / "nested" / "note.txt").read_text(
        encoding="utf-8"
    ) == "remote-dir"
