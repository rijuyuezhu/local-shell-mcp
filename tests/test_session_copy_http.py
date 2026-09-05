import asyncio
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from workgate.config.settings import get_settings
from workgate.ops.utils import session_copy as session_copy_module
from workgate.remote.transfer_gateway import TransferGatewayStore
from workgate.tool_session.store import AgentSession


def _endpoint(
    *, target: str, session_id: str, workdir: Path, machine: str | None = None
):
    return session_copy_module._Endpoint(
        session=AgentSession(
            session_id=session_id,
            target=target,  # type: ignore[arg-type]
            workdir=str(workdir),
            machine=machine,
            worker_session_id=("worker01" if machine else None),
            created_at=time.time(),
            updated_at=time.time(),
        )
    )


def _transfer_metadata() -> list[dict[str, object]]:
    rows = []
    for path in get_settings().remote_transfer_dir.glob("*.json"):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


@pytest.mark.asyncio
async def test_managed_failure_suspends_for_same_job_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    payload = b"managed-retry-payload"
    source_path = settings.workspace_root / "source.bin"
    source_path.write_bytes(payload)
    source = _endpoint(
        target="local",
        session_id="source01",
        workdir=settings.workspace_root,
    )
    destination = _endpoint(
        target="remote",
        session_id="dest0001",
        workdir=Path("/remote/workspace"),
        machine="worker-one",
    )

    async def fail_remote(*_args, **_kwargs):
        raise RuntimeError("simulated interrupted download")

    monkeypatch.setattr(
        session_copy_module, "_remote_raw_transfer_data", fail_remote
    )
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(RuntimeError, match="interrupted"):
        await session_copy_module._copy_file_http(
            source,
            "source.bin",
            destination,
            "destination.bin",
            stat={"path": "source.bin", "size": len(payload), "sha256": digest},
            overwrite=True,
            chunk_bytes=1024,
            progress=None,
            src_session_bound=False,
            dst_session_bound=True,
            resume_key="managed-job-1",
        )

    metadata = _transfer_metadata()
    assert len(metadata) == 1
    first = metadata[0]
    assert first["state"] == "ready"
    assert first["upload_token_hash"] is None
    assert first["download_token_hash"] is None
    transfer_id = str(first["transfer_id"])
    spool = settings.remote_transfer_dir / f"{transfer_id}.spool"
    assert spool.read_bytes() == payload

    store = TransferGatewayStore(settings)
    obj, upload, download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=digest,
        upload_worker=None,
        download_worker="worker-one",
        source_session_id="source01",
        destination_session_id="dest0001",
        resume_key="managed-job-1",
        snapshot_path=source_path,
    )
    assert obj.transfer_id == transfer_id
    assert obj.offset == len(payload)
    assert upload is None
    assert download is not None
    assert download.authorization


@pytest.mark.asyncio
async def test_foreground_failure_and_cancellation_remove_private_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    payload = b"cleanup-payload"
    (settings.workspace_root / "source.bin").write_bytes(payload)
    source = _endpoint(
        target="local",
        session_id="source02",
        workdir=settings.workspace_root,
    )
    destination = _endpoint(
        target="remote",
        session_id="dest0002",
        workdir=Path("/remote/workspace"),
        machine="worker-two",
    )
    digest = hashlib.sha256(payload).hexdigest()

    async def fail_remote(_endpoint, tool, _args):
        if tool == "transfer_http_abort_download":
            return {"removed": True}
        raise RuntimeError("foreground failure")

    monkeypatch.setattr(
        session_copy_module, "_remote_raw_transfer_data", fail_remote
    )
    with pytest.raises(RuntimeError, match="foreground"):
        await session_copy_module._copy_file_http(
            source,
            "source.bin",
            destination,
            "destination.bin",
            stat={"path": "source.bin", "size": len(payload), "sha256": digest},
            overwrite=True,
            chunk_bytes=1024,
            progress=None,
            src_session_bound=False,
            dst_session_bound=True,
            resume_key=None,
        )
    assert _transfer_metadata() == []
    assert list(settings.remote_transfer_dir.glob("*.spool")) == []

    async def cancel_remote(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        session_copy_module, "_remote_raw_transfer_data", cancel_remote
    )
    with pytest.raises(asyncio.CancelledError):
        await session_copy_module._copy_file_http(
            source,
            "source.bin",
            destination,
            "destination.bin",
            stat={"path": "source.bin", "size": len(payload), "sha256": digest},
            overwrite=True,
            chunk_bytes=1024,
            progress=None,
            src_session_bound=False,
            dst_session_bound=True,
            resume_key="managed-job-cancelled",
        )
    assert _transfer_metadata() == []
    assert list(settings.remote_transfer_dir.glob("*.spool")) == []


def test_http_selection_requires_config_threshold_and_worker_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    source = _endpoint(
        target="local",
        session_id="source03",
        workdir=settings.workspace_root,
    )
    destination = _endpoint(
        target="remote",
        session_id="dest0003",
        workdir=Path("/remote/workspace"),
        machine="worker-three",
    )
    configured = SimpleNamespace(
        remote_http_transfer_enabled=True,
        base_url="http://127.0.0.1:9000",
        remote_http_transfer_threshold_bytes=1024,
    )
    monkeypatch.setattr(session_copy_module, "get_settings", lambda: configured)
    monkeypatch.setattr(
        session_copy_module, "_worker_supports_http", lambda _endpoint: False
    )
    assert (
        session_copy_module._should_use_http_transfer(source, destination, 4096)
        is False
    )

    monkeypatch.setattr(
        session_copy_module, "_worker_supports_http", lambda _endpoint: True
    )
    assert (
        session_copy_module._should_use_http_transfer(source, destination, 1023)
        is False
    )
    assert (
        session_copy_module._should_use_http_transfer(source, destination, 1024)
        is True
    )

    configured.base_url = None
    assert (
        session_copy_module._should_use_http_transfer(source, destination, 4096)
        is False
    )


def test_endpoint_labels_json_and_worker_session_validation() -> None:
    settings = get_settings()
    local = _endpoint(
        target="local", session_id="local004", workdir=settings.workspace_root
    )
    remote = _endpoint(
        target="remote",
        session_id="remote04",
        workdir=Path("/remote"),
        machine="machine-four",
    )
    anonymous_remote = session_copy_module._Endpoint(
        AgentSession(
            session_id="remote05",
            target="remote",
            workdir="/remote",
            machine=None,
            worker_session_id=None,
            created_at=time.time(),
            updated_at=time.time(),
        )
    )
    assert local.label == "local"
    assert remote.label == "machine-four"
    assert anonymous_remote.label == "remote"
    assert session_copy_module._json_dict(7) == {"result": 7}
    assert (
        session_copy_module._worker_session_id(local, session_bound=True)
        is None
    )
    assert (
        session_copy_module._worker_session_id(remote, session_bound=True)
        == "worker01"
    )
    with pytest.raises(RuntimeError, match="missing worker_session_id"):
        session_copy_module._worker_session_id(
            anonymous_remote, session_bound=True
        )
    assert session_copy_module._worker_supports_http(local) is True


@pytest.mark.asyncio
async def test_remote_raw_errors_and_local_cleanup_shortcuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    local = _endpoint(
        target="local", session_id="local005", workdir=settings.workspace_root
    )
    remote = _endpoint(
        target="remote",
        session_id="remote06",
        workdir=Path("/remote"),
        machine="machine-six",
    )
    with pytest.raises(ValueError, match="require a remote session"):
        await session_copy_module._remote_raw_transfer_data(local, "tool", {})

    async def not_ok(*_args, **_kwargs):
        return {"ok": False, "message": "worker failed"}

    monkeypatch.setattr(session_copy_module, "call_remote_worker_tool", not_ok)
    with pytest.raises(RuntimeError, match="worker failed"):
        await session_copy_module._remote_raw_transfer_data(remote, "tool", {})

    async def nested_error(*_args, **_kwargs):
        return {
            "ok": True,
            "data": {
                "status": "error",
                "error_type": "transfer_error",
                "message": "nested failure",
            },
        }

    monkeypatch.setattr(
        session_copy_module, "call_remote_worker_tool", nested_error
    )
    with pytest.raises(RuntimeError, match="transfer_error: nested failure"):
        await session_copy_module._remote_raw_transfer_data(remote, "tool", {})

    with pytest.raises(ValueError, match="unsupported transfer tool"):
        await session_copy_module._endpoint_transfer_data(local, "unknown", {})
    await session_copy_module._cleanup_temp(local, None)
    await session_copy_module._abort_http_destination(
        local, "destination.bin", "t" * 24, session_bound=True
    )


def test_http_selection_rejects_local_and_same_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    configured = SimpleNamespace(
        remote_http_transfer_enabled=True,
        base_url="http://127.0.0.1:9000",
        remote_http_transfer_threshold_bytes=1,
    )
    monkeypatch.setattr(session_copy_module, "get_settings", lambda: configured)
    monkeypatch.setattr(
        session_copy_module, "_worker_supports_http", lambda _endpoint: True
    )
    local_one = _endpoint(
        target="local", session_id="local006", workdir=settings.workspace_root
    )
    local_two = _endpoint(
        target="local", session_id="local007", workdir=settings.workspace_root
    )
    assert (
        session_copy_module._should_use_http_transfer(local_one, local_two, 100)
        is False
    )
    remote_one = _endpoint(
        target="remote",
        session_id="remote07",
        workdir=Path("/remote"),
        machine="same-machine",
    )
    remote_two = _endpoint(
        target="remote",
        session_id="remote08",
        workdir=Path("/remote"),
        machine="same-machine",
    )
    assert (
        session_copy_module._should_use_http_transfer(
            remote_one, remote_two, 100
        )
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunk", "message"),
    [
        ({"offset": 1, "bytes": 1, "size": 2, "eof": False}, "offset mismatch"),
        ({"offset": 0, "bytes": 1, "size": 3, "eof": False}, "size changed"),
        ({"offset": 0, "bytes": 0, "size": 2, "eof": False}, "ended before"),
        ({"offset": 0, "bytes": 1, "size": 2, "eof": True}, "EOF marker"),
    ],
)
async def test_rpc_copy_rejects_inconsistent_source_chunks(
    monkeypatch: pytest.MonkeyPatch,
    chunk: dict[str, object],
    message: str,
) -> None:
    settings = get_settings()
    source = _endpoint(
        target="local", session_id="local008", workdir=settings.workspace_root
    )
    destination = _endpoint(
        target="local", session_id="local009", workdir=settings.workspace_root
    )
    calls = 0

    async def fake_endpoint(_endpoint, tool, _args, **_kwargs):
        nonlocal calls
        calls += 1
        if tool == "transfer_begin_write":
            return {"transfer_id": "x" * 32}
        if tool == "transfer_read_chunk":
            return chunk
        raise AssertionError(tool)

    async def no_abort(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        session_copy_module, "_endpoint_transfer_data", fake_endpoint
    )
    monkeypatch.setattr(session_copy_module, "_abort_transfer", no_abort)
    with pytest.raises(RuntimeError, match=message):
        await session_copy_module._copy_file_rpc(
            source,
            "source.bin",
            destination,
            "destination.bin",
            stat={"path": "source.bin", "size": 2, "sha256": "0" * 64},
            overwrite=True,
            chunk_bytes=1,
            progress=None,
            src_session_bound=True,
            dst_session_bound=True,
        )
    assert calls == 2


@pytest.mark.asyncio
async def test_copy_file_rejects_non_file_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    source = _endpoint(
        target="local", session_id="local010", workdir=settings.workspace_root
    )
    destination = _endpoint(
        target="local", session_id="local011", workdir=settings.workspace_root
    )

    async def directory_stat(*_args, **_kwargs):
        return {"type": "dir", "path": "source"}

    monkeypatch.setattr(
        session_copy_module, "_endpoint_transfer_data", directory_stat
    )
    with pytest.raises(ValueError, match="not a file"):
        await session_copy_module._copy_file(
            source,
            "source",
            destination,
            "destination",
            overwrite=True,
            chunk_size=1024,
        )
