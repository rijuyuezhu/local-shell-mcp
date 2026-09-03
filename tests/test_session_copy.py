import asyncio
import base64
import hashlib
from typing import Any

import pytest

import local_shell_mcp.ops.utils.remote_session as remote_session_utils
import local_shell_mcp.ops.utils.session_copy as session_copy_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.jobs import runtime as jobs_ops
from local_shell_mcp.ops.session import (
    session_change_cwd_execute,
    session_copy_execute,
)
from local_shell_mcp.tool_session.lifecycle import session_lifecycle_lock
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.local_handlers import (
    call_local_tool,
)
from local_shell_mcp.utils.serialization import to_jsonable

pytestmark = pytest.mark.usefixtures("managed_jobs_runtime_owner")


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
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
    local_args = dict(args)
    local_args.pop("workdir", None)
    local_args.pop("source_workdir", None)
    local_args.pop("destination_workdir", None)
    try:
        return {
            "ok": True,
            "data": to_jsonable(await call_local_tool(tool, local_args)),
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
@pytest.mark.parametrize("endpoint", ["SRC00001", "DST00001"])
async def test_foreground_copy_holds_both_endpoint_lifecycle_locks(
    monkeypatch, endpoint
):
    entered = asyncio.Event()
    release = asyncio.Event()
    contender_acquired = asyncio.Event()
    sentinel = object()

    async def fake_copy(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return sentinel

    async def contend_for_endpoint():
        async with session_lifecycle_lock(endpoint):
            contender_acquired.set()

    monkeypatch.setattr(
        session_copy_ops, "_session_copy_execute_unlocked", fake_copy
    )
    copy_task = asyncio.create_task(
        session_copy_ops.session_copy_execute(
            "SRC00001", "source.bin", "DST00001", "dest.bin"
        )
    )
    await entered.wait()
    contender = asyncio.create_task(contend_for_endpoint())
    await asyncio.sleep(0)

    assert not contender_acquired.is_set()
    release.set()
    assert await copy_task is sentinel
    await contender
    assert contender_acquired.is_set()


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
    assert result.cleanup_errors == []
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
    calls = _install_fake_remote(monkeypatch)
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
    transfer_tools = [tool for _, tool, _ in calls]
    assert "transfer_copy_file" in transfer_tools
    assert "transfer_read_chunk" not in transfer_tools
    assert "transfer_write_chunk" not in transfer_tools
    assert (root / "worker" / "dst" / "payload.txt").read_text(
        encoding="utf-8"
    ) == "same-machine"


@pytest.mark.asyncio
async def test_session_copy_remote_directory_same_machine_streams_archive_locally(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    calls = _install_fake_remote(monkeypatch)
    (root / "worker" / "src" / "tree" / "nested").mkdir(parents=True)
    (root / "worker" / "dst").mkdir(parents=True)
    (root / "worker" / "src" / "tree" / "nested" / "note.txt").write_text(
        "same-worker-dir", encoding="utf-8"
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
        "tree",
        remote_dst.session_id,
        "tree-copy",
        kind="dir",
        chunk_size=128,
    )

    transfer_tools = [tool for _, tool, _ in calls]
    assert result.relation.route == "remote_to_remote_same_machine"
    assert result.entries is not None and result.entries >= 1
    assert "transfer_copy_file" in transfer_tools
    assert "transfer_read_chunk" not in transfer_tools
    assert "transfer_write_chunk" not in transfer_tools
    assert (
        root / "worker" / "dst" / "tree-copy" / "nested" / "note.txt"
    ).read_text(encoding="utf-8") == "same-worker-dir"


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


@pytest.mark.asyncio
async def test_session_copy_aborts_destination_write_on_cancellation(
    tmp_path, monkeypatch
):
    _root, store = _workspace(tmp_path, monkeypatch)
    src = store.create_session(workdir=".")
    dst = store.create_session(workdir=".")
    aborted: list[dict[str, Any]] = []

    async def fake_transfer(_endpoint, tool, args, *, session_bound=True):
        _ = session_bound
        if tool == "transfer_stat":
            return {
                "path": "source.bin",
                "type": "file",
                "size": 3,
                "modified": 0.0,
                "sha256": hashlib.sha256(b"abc").hexdigest(),
            }
        if tool == "transfer_begin_write":
            return {"transfer_id": "transfer-1"}
        if tool == "transfer_read_chunk":
            raise asyncio.CancelledError()
        if tool == "transfer_abort_write":
            aborted.append(dict(args))
            return {"deleted": True}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(
        session_copy_ops, "_endpoint_transfer_data", fake_transfer
    )

    with pytest.raises(asyncio.CancelledError):
        await session_copy_execute(
            src.session_id,
            "source.bin",
            dst.session_id,
            "dest.bin",
            kind="file",
        )

    assert aborted == [{"path": "dest.bin", "transfer_id": "transfer-1"}]


@pytest.mark.asyncio
async def test_cancelled_directory_copy_cleans_both_archive_sides(
    tmp_path, monkeypatch
):
    _root, store = _workspace(tmp_path, monkeypatch)
    src = store.create_session(workdir=".")
    dst = store.create_session(workdir=".")
    aborted: list[dict[str, Any]] = []
    deleted: list[str] = []

    async def fake_transfer(_endpoint, tool, args, *, session_bound=True):
        _ = session_bound
        if tool == "transfer_stat" and args["path"] == "tree":
            return {
                "path": "tree",
                "type": "dir",
                "size": None,
                "modified": 0.0,
                "sha256": None,
            }
        if tool == "transfer_pack_dir":
            return {
                "path": "tree",
                "archive_path": "source.tar.gz",
                "bytes": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
                "compression": "gz",
            }
        if tool == "transfer_alloc_temp_path":
            return {"path": "destination.tar.gz"}
        if tool == "transfer_stat" and args["path"] == "source.tar.gz":
            return {
                "path": "source.tar.gz",
                "type": "file",
                "size": 1,
                "modified": 0.0,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            }
        if tool == "transfer_begin_write":
            return {"transfer_id": "transfer-2"}
        if tool == "transfer_read_chunk":
            raise asyncio.CancelledError()
        if tool == "transfer_abort_write":
            aborted.append(dict(args))
            return {"deleted": True}
        if tool == "transfer_delete_temp_path":
            deleted.append(str(args["path"]))
            return {"deleted": True}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(
        session_copy_ops, "_endpoint_transfer_data", fake_transfer
    )

    with pytest.raises(asyncio.CancelledError):
        await session_copy_execute(
            src.session_id,
            "tree",
            dst.session_id,
            "tree-copy",
            kind="dir",
        )

    assert aborted == [
        {"path": "destination.tar.gz", "transfer_id": "transfer-2"}
    ]
    assert set(deleted) == {"source.tar.gz", "destination.tar.gz"}


@pytest.mark.asyncio
async def test_directory_copy_surfaces_post_commit_cleanup_errors(
    tmp_path, monkeypatch
):
    _root, store = _workspace(tmp_path, monkeypatch)
    src = store.create_session(workdir=".")
    dst = store.create_session(workdir=".")
    payload = b"x"
    digest = hashlib.sha256(payload).hexdigest()

    async def fake_transfer(_endpoint, tool, args, *, session_bound=True):
        _ = session_bound
        if tool == "transfer_stat" and args["path"] == "tree":
            return {
                "path": "tree",
                "type": "dir",
                "size": None,
                "modified": 0.0,
                "sha256": None,
            }
        if tool == "transfer_pack_dir":
            return {
                "path": "tree",
                "archive_path": "source.tar.gz",
                "bytes": 1,
                "sha256": digest,
                "compression": "gz",
            }
        if tool == "transfer_alloc_temp_path":
            return {"path": "destination.tar.gz"}
        if tool == "transfer_stat":
            return {
                "path": "source.tar.gz",
                "type": "file",
                "size": 1,
                "modified": 0.0,
                "sha256": digest,
            }
        if tool == "transfer_begin_write":
            return {"transfer_id": "transfer-3"}
        if tool == "transfer_read_chunk":
            return {
                "path": "source.tar.gz",
                "offset": 0,
                "bytes": 1,
                "size": 1,
                "eof": True,
                "sha256": digest,
                "data_b64": base64.b64encode(payload).decode("ascii"),
            }
        if tool == "transfer_write_chunk":
            return {"bytes": 1}
        if tool == "transfer_finish_write":
            return {
                "path": "destination.tar.gz",
                "bytes": 1,
                "sha256": digest,
                "completed": True,
            }
        if tool == "transfer_unpack_archive":
            return {
                "path": "tree-copy",
                "archive_path": "destination.tar.gz",
                "entries": 1,
                "completed": True,
                "archive_deleted": False,
                "backup_deleted": False,
                "cleanup_errors": ["backup cleanup failed"],
            }
        if tool == "transfer_delete_temp_path":
            return {"deleted": True}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(
        session_copy_ops, "_endpoint_transfer_data", fake_transfer
    )

    result = await session_copy_execute(
        src.session_id,
        "tree",
        dst.session_id,
        "tree-copy",
        kind="dir",
    )

    assert result.cleanup_errors == ["backup cleanup failed"]


@pytest.mark.asyncio
async def test_session_copy_background_job_reports_progress_and_result(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "dst").mkdir()
    payload = b"background-copy" * 2048
    (root / "src" / "payload.bin").write_bytes(payload)
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    async def no_shells():
        return set()

    monkeypatch.setattr(
        jobs_ops, "authoritative_persistent_shell_ids_execute", no_shells
    )
    started = await session_copy_execute(
        src.session_id,
        "payload.bin",
        dst.session_id,
        "copied.bin",
        chunk_size=1024,
        background=True,
    )
    assert started.kind == "managed"
    assert started.status == "running"

    tail = None
    for _ in range(200):
        await asyncio.sleep(0.01)
        tail = await jobs_ops.job_tail_execute(src.session_id, started.job_id)
        if tail.job.status == "succeeded":
            break
    assert tail is not None
    assert tail.job.status == "succeeded"
    assert tail.job.progress is not None
    assert tail.job.progress["phase"] == "completed"
    assert tail.job.progress["bytes_transferred"] == len(payload)
    assert tail.job.result is not None
    assert tail.job.result["kind"] == "file"
    relation = tail.job.result["relation"]
    assert isinstance(relation, dict)
    assert relation["route"] == "local_to_local"
    assert "copy completed" in tail.output
    assert (root / "dst" / "copied.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_session_copy_background_pins_endpoint_workdirs_across_cwd_changes(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    for directory in ("src-original", "dst-original", "src-new", "dst-new"):
        (root / directory).mkdir()
    original_payload = b"original-background-payload" * 1024
    replacement_payload = b"replacement-after-cwd-change" * 1024
    (root / "src-original" / "payload.bin").write_bytes(original_payload)
    (root / "src-new" / "payload.bin").write_bytes(replacement_payload)
    src = store.create_session(workdir="src-original")
    dst = store.create_session(workdir="dst-original")
    first_chunk_read = asyncio.Event()
    resume_copy = asyncio.Event()
    original_transfer = session_copy_ops._endpoint_transfer_data

    async def no_shells():
        return set()

    async def pause_after_first_chunk(
        endpoint, tool, args, *, session_bound=True
    ):
        result = await original_transfer(
            endpoint, tool, args, session_bound=session_bound
        )
        if (
            tool == "transfer_read_chunk"
            and endpoint.session.session_id == src.session_id
            and int(args.get("offset") or 0) == 0
        ):
            first_chunk_read.set()
            await resume_copy.wait()
        return result

    monkeypatch.setattr(
        jobs_ops, "authoritative_persistent_shell_ids_execute", no_shells
    )
    monkeypatch.setattr(
        session_copy_ops, "_endpoint_transfer_data", pause_after_first_chunk
    )
    await session_copy_execute(
        src.session_id,
        "payload.bin",
        dst.session_id,
        "copied.bin",
        chunk_size=1024,
        background=True,
    )
    await asyncio.wait_for(first_chunk_read.wait(), timeout=2)

    await session_change_cwd_execute(src.session_id, "src-new")
    await session_change_cwd_execute(dst.session_id, "dst-new")
    resume_copy.set()

    completed = None
    for _ in range(300):
        await asyncio.sleep(0.01)
        completed = (await jobs_ops.job_list_execute(src.session_id)).jobs[0]
        if completed.status == "succeeded":
            break
    assert completed is not None
    assert completed.status == "succeeded"
    assert (
        root / "dst-original" / "copied.bin"
    ).read_bytes() == original_payload
    assert not (root / "dst-new" / "copied.bin").exists()
    assert not list((root / "dst-new").glob(".*local-shell-mcp-transfer*"))


@pytest.mark.asyncio
async def test_session_copy_background_cancel_aborts_transaction(
    tmp_path, monkeypatch
):
    _root, store = _workspace(tmp_path, monkeypatch)
    src = store.create_session(workdir=".")
    dst = store.create_session(workdir=".")
    read_started = asyncio.Event()
    hold_read = asyncio.Event()
    aborted: list[dict[str, Any]] = []

    async def no_shells():
        return set()

    async def fake_transfer(_endpoint, tool, args, *, session_bound=True):
        _ = session_bound
        if tool == "transfer_stat":
            return {
                "path": "source.bin",
                "type": "file",
                "size": 3,
                "modified": 0.0,
                "sha256": hashlib.sha256(b"abc").hexdigest(),
            }
        if tool == "transfer_begin_write":
            return {"transfer_id": "transfer-background"}
        if tool == "transfer_read_chunk":
            read_started.set()
            await hold_read.wait()
            raise AssertionError("cancelled read unexpectedly resumed")
        if tool == "transfer_abort_write":
            aborted.append(dict(args))
            return {"deleted": True}
        raise AssertionError(f"unexpected tool: {tool}")

    monkeypatch.setattr(
        jobs_ops, "authoritative_persistent_shell_ids_execute", no_shells
    )
    monkeypatch.setattr(
        session_copy_ops, "_endpoint_transfer_data", fake_transfer
    )
    started = await session_copy_execute(
        src.session_id,
        "source.bin",
        dst.session_id,
        "dest.bin",
        kind="file",
        background=True,
    )
    await asyncio.wait_for(read_started.wait(), timeout=2)

    stopped = await jobs_ops.job_stop_execute(src.session_id, started.job_id)
    assert stopped.killed is True
    assert stopped.job.status == "stopped"
    assert aborted == [
        {"path": "dest.bin", "transfer_id": "transfer-background"}
    ]


@pytest.mark.asyncio
async def test_session_copy_background_retry_reuses_durable_payload(
    tmp_path, monkeypatch
):
    root, store = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "dst").mkdir()
    src = store.create_session(workdir="src")
    dst = store.create_session(workdir="dst")

    async def no_shells():
        return set()

    monkeypatch.setattr(
        jobs_ops, "authoritative_persistent_shell_ids_execute", no_shells
    )
    started = await session_copy_execute(
        src.session_id,
        "later.bin",
        dst.session_id,
        "copied.bin",
        background=True,
    )

    failed = None
    for _ in range(200):
        await asyncio.sleep(0.01)
        failed = (await jobs_ops.job_list_execute(src.session_id)).jobs[0]
        if failed.status == "failed":
            break
    assert failed is not None
    assert failed.status == "failed"
    assert "FileNotFoundError" in str(failed.error)

    payload = b"available-on-retry"
    (root / "src" / "later.bin").write_bytes(payload)
    retried = await jobs_ops.job_retry_execute(src.session_id, started.job_id)
    assert retried.attempts == 2

    completed = retried
    for _ in range(200):
        await asyncio.sleep(0.01)
        completed = (await jobs_ops.job_list_execute(src.session_id)).jobs[0]
        if completed.status == "succeeded":
            break
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["bytes"] == len(payload)
    assert (root / "dst" / "copied.bin").read_bytes() == payload
