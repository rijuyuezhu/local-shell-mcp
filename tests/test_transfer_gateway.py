from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.http.request_limits import (
    RequestBodyLimitMiddleware,
)
from local_shell_mcp.ops.transfer import (
    transfer_begin_write,
    transfer_finish_write,
    transfer_write_bytes,
)
from local_shell_mcp.remote import transfer_gateway as gateway_module
from local_shell_mcp.remote.transfer_gateway import (
    TransferGatewayError,
    TransferGatewayStore,
    TransferGrant,
    build_transfer_gateway_router,
)
from local_shell_mcp.remote_worker.http_transfer import (
    WorkerHTTPTransferError,
    _validate_url,
)


def _client() -> TestClient:
    return TestClient(Starlette(routes=list(build_transfer_gateway_router())))


def _headers(grant: TransferGrant) -> dict[str, str]:
    return {
        "Authorization": grant.authorization,
        "X-Local-Shell-MCP-Worker": grant.worker,
        "X-Local-Shell-MCP-Transfer-Direction": grant.direction,
    }


def _prepare_upload(
    payload: bytes, *, resume_key: str | None = None
) -> tuple[TransferGatewayStore, TransferGrant, TransferGrant]:
    store = TransferGatewayStore()
    _obj, upload, download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        upload_worker="source-worker",
        download_worker="destination-worker",
        source_session_id="source-session",
        destination_session_id="destination-session",
        resume_key=resume_key,
    )
    assert upload is not None
    assert download is not None
    return store, upload, download


def _put_chunk(
    client: TestClient,
    grant: TransferGrant,
    payload: bytes,
    *,
    start: int,
    total: int,
):
    end = start + len(payload) - 1
    headers = _headers(grant)
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{total}",
            "X-Content-SHA256": hashlib.sha256(payload).hexdigest(),
        }
    )
    return client.put(grant.url, content=payload, headers=headers)


def test_upload_resume_replay_download_and_worker_binding() -> None:
    payload = b"abcdef"
    store, upload, download = _prepare_upload(payload)
    with _client() as client:
        missing = client.head(upload.url)
        assert missing.status_code == 401

        wrong_worker_headers = _headers(upload)
        wrong_worker_headers["X-Local-Shell-MCP-Worker"] = "other-worker"
        wrong_worker = client.head(upload.url, headers=wrong_worker_headers)
        assert wrong_worker.status_code == 401

        status = client.head(upload.url, headers=_headers(upload))
        assert status.status_code == 200
        assert status.headers["x-transfer-offset"] == "0"
        assert status.headers["x-transfer-state"] == "uploading"

        first = _put_chunk(
            client, upload, payload[:3], start=0, total=len(payload)
        )
        assert first.status_code == 200
        assert first.json() == {
            "offset": 3,
            "state": "uploading",
            "replayed": False,
        }

        replay = _put_chunk(
            client, upload, payload[:3], start=0, total=len(payload)
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True

        conflict = _put_chunk(
            client, upload, b"xyz", start=0, total=len(payload)
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "completed chunk cannot be replayed"

        second = _put_chunk(
            client, upload, payload[3:], start=3, total=len(payload)
        )
        assert second.status_code == 200
        assert second.json() == {
            "offset": 6,
            "state": "ready",
            "replayed": False,
        }

        no_range = client.get(download.url, headers=_headers(download))
        assert no_range.status_code == 422

        first_range_headers = _headers(download)
        first_range_headers["Range"] = "bytes=0-2"
        first_range = client.get(download.url, headers=first_range_headers)
        assert first_range.status_code == 206
        assert first_range.content == payload[:3]
        assert first_range.headers["content-range"] == "bytes 0-2/6"

        second_range_headers = _headers(download)
        second_range_headers["Range"] = "bytes=3-"
        second_range = client.get(download.url, headers=second_range_headers)
        assert second_range.status_code == 206
        assert second_range.content == payload[3:]
        assert (
            second_range.headers["x-content-sha256"]
            == hashlib.sha256(payload).hexdigest()
        )

    obj = store.object(upload.transfer_id)
    assert obj.path.read_bytes() == payload


def test_resume_rotates_capability_and_recovers_stale_claim(
    monkeypatch,
) -> None:
    payload = b"abcdefgh"
    store, first_upload, _download = _prepare_upload(
        payload, resume_key="job-1"
    )
    with _client() as client:
        response = _put_chunk(
            client, first_upload, payload[:4], start=0, total=len(payload)
        )
        assert response.status_code == 200

    obj, second_upload, second_download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        upload_worker="source-worker",
        download_worker="destination-worker",
        source_session_id="source-session",
        destination_session_id="destination-session",
        resume_key="job-1",
    )
    assert second_upload is not None
    assert second_download is not None
    assert obj.transfer_id == first_upload.transfer_id
    assert obj.offset == 4
    assert second_upload.authorization != first_upload.authorization

    with _client() as client:
        assert (
            client.head(
                first_upload.url, headers=_headers(first_upload)
            ).status_code
            == 401
        )
        resumed = client.head(
            second_upload.url, headers=_headers(second_upload)
        )
        assert resumed.status_code == 200
        assert resumed.headers["x-transfer-offset"] == "4"

    _data, first_claim = store.begin_claim(obj.transfer_id, "upload")
    monkeypatch.setattr(gateway_module, "_PROCESS_NONCE", "new-process-nonce")
    _data, recovered_claim = store.begin_claim(obj.transfer_id, "upload")
    assert recovered_claim != first_claim
    store.release_claim(obj.transfer_id, recovered_claim)


def test_snapshot_is_private_immutable_and_token_is_not_persisted(
    tmp_path,
) -> None:
    payload = b"snapshot-payload"
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    store = TransferGatewayStore()
    obj, upload, download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        upload_worker=None,
        download_worker="destination-worker",
        source_session_id="source-session",
        destination_session_id="destination-session",
        snapshot_path=source,
    )
    assert upload is None
    assert download is not None
    assert obj.state == "ready"
    source.write_bytes(b"changed-after-snapshot")
    assert obj.path.read_bytes() == payload

    metadata_path = store.root / f"{obj.transfer_id}.json"
    metadata = metadata_path.read_text(encoding="utf-8")
    token = download.authorization.split(" ", 1)[1]
    assert token not in metadata
    assert download.authorization not in metadata
    if os.name != "nt":
        assert stat_mode(store.root) == 0o700
        assert stat_mode(metadata_path) == 0o600
        assert stat_mode(obj.path) == 0o600


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_rejects_expired_grant_bad_ranges_and_digest_mismatch() -> None:
    payload = b"abcdef"
    store, upload, _download = _prepare_upload(payload)
    with _client() as client:
        bad_total = _put_chunk(client, upload, b"abc", start=0, total=7)
        assert bad_total.status_code == 422

        too_far = _put_chunk(client, upload, b"abcdefg", start=0, total=6)
        assert too_far.status_code == 422

        headers = _headers(upload)
        headers.update(
            {
                "Content-Range": "bytes 0-2/6",
                "X-Content-SHA256": hashlib.sha256(b"other").hexdigest(),
            }
        )
        bad_digest = client.put(upload.url, content=b"abc", headers=headers)
        assert bad_digest.status_code == 422
        assert store.status(upload.transfer_id)["offset"] == 0

        metadata = store._load(upload.transfer_id)
        metadata["expires_at"] = 0
        store._save(metadata)
        expired = client.head(upload.url, headers=_headers(upload))
        assert expired.status_code == 410


def test_quota_resume_metadata_and_traversal_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_HTTP_TRANSFER_MAX_ACTIVE", "1")
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_REMOTE_HTTP_TRANSFER_MAX_SPOOL_BYTES", "16"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_REMOTE_HTTP_TRANSFER_THRESHOLD_BYTES", "1"
    )
    clear_settings_cache()
    store = TransferGatewayStore(get_settings())
    payload = b"12345678"
    obj, _upload, _download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        upload_worker="one",
        download_worker=None,
        source_session_id="source",
        destination_session_id="destination",
        resume_key="resume",
    )
    with pytest.raises(TransferGatewayError, match="maximum active"):
        store.prepare(
            expected_bytes=1,
            expected_sha256=hashlib.sha256(b"x").hexdigest(),
            upload_worker="two",
            download_worker=None,
            source_session_id="source-2",
            destination_session_id="destination-2",
        )
    with pytest.raises(TransferGatewayError, match="does not match"):
        store.prepare(
            expected_bytes=7,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_worker="one",
            download_worker=None,
            source_session_id="source",
            destination_session_id="destination",
            resume_key="resume",
        )
    with pytest.raises(TransferGatewayError, match="identifier"):
        store.status("../escape")

    terminal = store._load(obj.transfer_id)
    terminal["state"] = "consumed"
    store._save(terminal)
    store._reserve_locked(1)
    store.release_claim(obj.transfer_id, "x" * 24)


def test_prepare_rotates_a_colliding_transfer_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TransferGatewayStore()
    colliding = "c" * 24
    rotated = "r" * 24
    store._metadata_path(colliding).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        store, "_new_transfer_id", lambda _resume_key: colliding
    )
    monkeypatch.setattr(
        gateway_module.secrets, "token_urlsafe", lambda _size: rotated
    )
    obj, _upload, _download = store.prepare(
        expected_bytes=1,
        expected_sha256=hashlib.sha256(b"x").hexdigest(),
        upload_worker="worker",
        download_worker=None,
        source_session_id="source",
        destination_session_id="destination",
    )
    assert obj.transfer_id == rotated


def test_transaction_writer_resumes_contiguous_partial_file() -> None:
    settings = get_settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    first = transfer_begin_write("destination.bin", True, 6, "stable-transfer")
    transfer_write_bytes("destination.bin", first.transfer_id, 0, b"abc")
    resumed = transfer_begin_write(
        "destination.bin", True, 6, "stable-transfer"
    )
    assert resumed.resumed is True
    assert resumed.offset == 3
    transfer_write_bytes("destination.bin", resumed.transfer_id, 3, b"def")
    finished = transfer_finish_write(
        "destination.bin",
        resumed.transfer_id,
        6,
        hashlib.sha256(b"abcdef").hexdigest(),
    )
    assert finished.completed is True
    assert (
        settings.workspace_root / "destination.bin"
    ).read_bytes() == b"abcdef"


def test_request_body_limit_bypass_is_exact() -> None:
    exact: dict[str, Any] = {
        "type": "http",
        "method": "PUT",
        "path": "/remote/transfer/abcdefghijklmnopqrstuvwx",
    }
    assert RequestBodyLimitMiddleware._is_streaming_transfer_put(exact) is True
    for scope in (
        {**exact, "method": "POST"},
        {**exact, "path": "/remote/transfer/id/extra"},
        {**exact, "path": "/remote/transfers/id"},
        {**exact, "path": "/remote/transfer/"},
    ):
        assert (
            RequestBodyLimitMiddleware._is_streaming_transfer_put(scope)
            is False
        )


def test_worker_rejects_cross_origin_and_credential_urls() -> None:
    controller = "https://controller.example:8443"
    assert (
        _validate_url(
            "https://controller.example:8443/remote/transfer/abcdefghijklmnopqrstuvwx",
            controller,
        ).netloc
        == "controller.example:8443"
    )
    invalid = (
        "http://controller.example:8443/remote/transfer/abcdefghijklmnopqrstuvwx",
        "https://other.example:8443/remote/transfer/abcdefghijklmnopqrstuvwx",
        "https://user:pass@controller.example:8443/remote/transfer/abcdefghijklmnopqrstuvwx",
        "https://controller.example:8443/remote/transfer/abcdefghijklmnopqrstuvwx?token=secret",
        "https://controller.example:8443/remote/transfer/../escape",
    )
    for url in invalid:
        with pytest.raises(WorkerHTTPTransferError):
            _validate_url(url, controller)


def test_snapshot_symlink_is_rejected(tmp_path) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(target)
    except OSError, NotImplementedError:
        pytest.skip("symlinks are unavailable")
    store = TransferGatewayStore()
    with pytest.raises((OSError, TransferGatewayError)):
        store.prepare(
            expected_bytes=6,
            expected_sha256=hashlib.sha256(b"target").hexdigest(),
            upload_worker=None,
            download_worker="worker",
            source_session_id="source",
            destination_session_id="destination",
            snapshot_path=link,
        )


def test_spool_symlink_replacement_is_rejected(tmp_path) -> None:
    payload = b"payload"
    store, upload, _download = _prepare_upload(payload)
    spool = store.root / f"{upload.transfer_id}.spool"
    target = tmp_path / "target.bin"
    target.write_bytes(payload)
    spool.unlink()
    try:
        spool.symlink_to(target)
    except OSError, NotImplementedError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(TransferGatewayError, match="unsafe"):
        store.object(upload.transfer_id, require_ready=False)


def test_spool_regular_file_replacement_is_identity_rejected() -> None:
    payload = b"payload"
    replacement = b"attack!"
    assert len(replacement) == len(payload)
    store, upload, _download = _prepare_upload(payload)
    spool = store.root / f"{upload.transfer_id}.spool"
    spool.unlink()
    spool.write_bytes(replacement)
    with pytest.raises(TransferGatewayError, match="identity changed"):
        store.object(upload.transfer_id, require_ready=False)

    _data, claim = store.begin_claim(upload.transfer_id, "upload")
    chunk_path = store._chunk_path(upload.transfer_id, claim)
    chunk_path.write_bytes(payload)
    with pytest.raises(TransferGatewayError, match="identity changed"):
        store.commit_chunk(
            upload.transfer_id,
            claim,
            chunk_path,
            0,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    assert spool.read_bytes() == replacement
    store.release_claim(upload.transfer_id, claim)


def test_metadata_is_valid_json_without_private_absolute_source_path(
    tmp_path,
) -> None:
    payload = b"payload"
    source = tmp_path / "private" / "source.bin"
    source.parent.mkdir()
    source.write_bytes(payload)
    store = TransferGatewayStore()
    obj, _upload, _download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        upload_worker=None,
        download_worker="worker",
        source_session_id="source-session",
        destination_session_id="destination-session",
        snapshot_path=source,
    )
    metadata_text = (store.root / f"{obj.transfer_id}.json").read_text(
        encoding="utf-8"
    )
    json.loads(metadata_text)
    assert str(source) not in metadata_text


def test_store_rejects_corrupt_metadata_and_invalid_prepare_values() -> None:
    store = TransferGatewayStore()
    valid_id = "m" * 24
    with pytest.raises(TransferGatewayError, match="claim"):
        store._chunk_path(valid_id, "bad/claim")
    with pytest.raises(TransferGatewayError, match="not found"):
        store._load(valid_id)

    metadata_path = store._metadata_path(valid_id)
    metadata_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(TransferGatewayError, match="unreadable"):
        store._load(valid_id)
    metadata_path.write_text("[]", encoding="utf-8")
    with pytest.raises(TransferGatewayError, match="unsupported"):
        store._load(valid_id)
    metadata_path.write_text(
        json.dumps({"version": 1, "transfer_id": "n" * 24}), encoding="utf-8"
    )
    with pytest.raises(TransferGatewayError, match="identity mismatch"):
        store._load(valid_id)

    invalid_json = store.root / "invalid.json"
    invalid_json.write_text("not-json", encoding="utf-8")
    unsupported = store.root / "unsupported.json"
    unsupported.write_text("[]", encoding="utf-8")
    invalid_identity = store.root / "invalid-identity.json"
    invalid_identity.write_text(
        json.dumps({"version": 1, "transfer_id": "bad/id"}), encoding="utf-8"
    )
    rows = list(store._iter_metadata())
    assert all(isinstance(row, dict) for row in rows)
    store._cleanup_expired_locked(time.time())
    assert invalid_identity.exists()

    with pytest.raises(TransferGatewayError, match="non-negative"):
        store.prepare(
            expected_bytes=-1,
            expected_sha256="0" * 64,
            upload_worker="worker",
            download_worker=None,
            source_session_id="source",
            destination_session_id="destination",
        )
    with pytest.raises(TransferGatewayError, match="spool limit"):
        store.prepare(
            expected_bytes=store.settings.remote_http_transfer_max_spool_bytes
            + 1,
            expected_sha256="0" * 64,
            upload_worker="worker",
            download_worker=None,
            source_session_id="source",
            destination_session_id="destination",
        )
    with pytest.raises(TransferGatewayError, match="digest is invalid"):
        store.prepare(
            expected_bytes=1,
            expected_sha256="invalid",
            upload_worker="worker",
            download_worker=None,
            source_session_id="source",
            destination_session_id="destination",
        )


def test_store_cleanup_quota_and_resume_spool_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_HTTP_TRANSFER_MAX_ACTIVE", "10")
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_REMOTE_HTTP_TRANSFER_MAX_SPOOL_BYTES", "8"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_REMOTE_HTTP_TRANSFER_THRESHOLD_BYTES", "1"
    )
    clear_settings_cache()
    store = TransferGatewayStore(get_settings())
    payload = b"12345678"
    obj, _upload, _download = store.prepare(
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        upload_worker="worker",
        download_worker=None,
        source_session_id="source",
        destination_session_id="destination",
        resume_key="resume-integrity",
    )
    with pytest.raises(TransferGatewayError, match="quota"):
        store.prepare(
            expected_bytes=1,
            expected_sha256=hashlib.sha256(b"x").hexdigest(),
            upload_worker="worker-two",
            download_worker=None,
            source_session_id="source-two",
            destination_session_id="destination-two",
        )

    spool = obj.path
    spool.write_bytes(b"x")
    with pytest.raises(TransferGatewayError, match="identity changed"):
        store.prepare(
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_worker="worker",
            download_worker=None,
            source_session_id="source",
            destination_session_id="destination",
            resume_key="resume-integrity",
        )
    spool.unlink()
    with pytest.raises(TransferGatewayError, match="missing or unsafe"):
        store.prepare(
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_worker="worker",
            download_worker=None,
            source_session_id="source",
            destination_session_id="destination",
            resume_key="resume-integrity",
        )

    metadata = store._load(obj.transfer_id)
    metadata["expires_at"] = 0
    store._save(metadata)
    stale_chunk = store.root / f".{obj.transfer_id}.{'z' * 24}.chunk"
    stale_chunk.write_bytes(b"stale")
    os.utime(stale_chunk, (0, 0))
    store._cleanup_expired_locked(time.time())
    assert not store._metadata_path(obj.transfer_id).exists()
    assert not stale_chunk.exists()


def test_snapshot_change_and_digest_mismatch_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"snapshot")
    store = TransferGatewayStore()
    identities = iter([(1,), (2,)])
    monkeypatch.setattr(
        gateway_module,
        "_stable_source_identity",
        lambda _stat: next(identities),
    )
    with pytest.raises(TransferGatewayError, match="changed"):
        store.prepare(
            expected_bytes=8,
            expected_sha256=hashlib.sha256(b"snapshot").hexdigest(),
            upload_worker=None,
            download_worker="worker",
            source_session_id="source",
            destination_session_id="destination",
            snapshot_path=source,
        )
    assert list(store.root.glob("*.spool")) == []

    monkeypatch.undo()
    store = TransferGatewayStore()
    with pytest.raises(TransferGatewayError, match="digest mismatch"):
        store.prepare(
            expected_bytes=8,
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
            upload_worker=None,
            download_worker="worker",
            source_session_id="source",
            destination_session_id="destination",
            snapshot_path=source,
        )
    assert list(store.root.glob("*.spool")) == []


def test_terminal_auth_claim_conflict_and_chunk_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"abcdef"
    store, upload, _download = _prepare_upload(payload)
    with pytest.raises(TransferGatewayError, match="required"):
        store.authenticate(
            upload.transfer_id, "Bearer invalid", upload.worker, "upload"
        )
    with pytest.raises(TransferGatewayError, match="required"):
        store.authenticate(
            upload.transfer_id, "Transfer ", upload.worker, "upload"
        )

    metadata = store._load(upload.transfer_id)
    metadata["state"] = "consumed"
    store._save(metadata)
    with pytest.raises(TransferGatewayError, match="no longer active"):
        store.authenticate(
            upload.transfer_id, upload.authorization, upload.worker, "upload"
        )
    metadata["state"] = "uploading"
    store._save(metadata)

    _data, claim = store.begin_claim(upload.transfer_id, "upload")
    with pytest.raises(TransferGatewayError, match="active claim"):
        store.begin_claim(upload.transfer_id, "upload")
    chunk_path = store._chunk_path(upload.transfer_id, claim)
    chunk_path.write_bytes(b"abc")
    with pytest.raises(TransferGatewayError, match="claim changed"):
        store.commit_chunk(
            upload.transfer_id,
            "x" * 24,
            chunk_path,
            0,
            3,
            hashlib.sha256(b"abc").hexdigest(),
        )
    store.release_claim(upload.transfer_id, claim)

    _data, claim = store.begin_claim(upload.transfer_id, "upload")
    with pytest.raises(TransferGatewayError, match="offset conflict"):
        store.commit_chunk(
            upload.transfer_id,
            claim,
            chunk_path,
            1,
            4,
            hashlib.sha256(b"abc").hexdigest(),
        )
    store.release_claim(upload.transfer_id, claim)

    _data, claim = store.begin_claim(upload.transfer_id, "upload")
    calls = 0
    real_fsync = gateway_module.os.fsync

    def flaky_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(gateway_module.os, "fsync", flaky_fsync)
    with pytest.raises(TransferGatewayError, match="spool write failed"):
        store.commit_chunk(
            upload.transfer_id,
            claim,
            chunk_path,
            0,
            3,
            hashlib.sha256(b"abc").hexdigest(),
        )
    assert store._spool_path(upload.transfer_id).stat().st_size == 0
    store.release_claim(upload.transfer_id, claim)


def test_final_digest_failure_and_object_state_checks() -> None:
    expected = b"good"
    actual = b"evil"
    store, upload, _download = _prepare_upload(expected)
    with pytest.raises(TransferGatewayError, match="not ready"):
        store.object(upload.transfer_id)
    _data, claim = store.begin_claim(upload.transfer_id, "upload")
    chunk_path = store._chunk_path(upload.transfer_id, claim)
    chunk_path.write_bytes(actual)
    with pytest.raises(TransferGatewayError, match="digest mismatch"):
        store.commit_chunk(
            upload.transfer_id,
            claim,
            chunk_path,
            0,
            len(actual),
            hashlib.sha256(actual).hexdigest(),
        )
    assert store.status(upload.transfer_id)["state"] == "failed"

    other_store, other_upload, _download = _prepare_upload(b"abc")
    other_store._spool_path(other_upload.transfer_id).write_bytes(b"wrong-size")
    with pytest.raises(TransferGatewayError) as raised:
        other_store.object(other_upload.transfer_id, require_ready=False)
    assert str(raised.value) in {
        "transfer spool identity changed",
        "transfer spool size changed",
    }


def test_gateway_route_malformed_headers_and_range_errors() -> None:
    payload = b"abcdef"
    store, upload, download = _prepare_upload(payload)
    with _client() as client:
        invalid_direction = _headers(upload)
        invalid_direction["X-Local-Shell-MCP-Transfer-Direction"] = "sideways"
        assert (
            client.head(upload.url, headers=invalid_direction).status_code
            == 422
        )

        missing_range = client.put(
            upload.url, content=b"abc", headers=_headers(upload)
        )
        assert missing_range.status_code == 422

        malformed = _headers(upload)
        malformed.update(
            {
                "Content-Range": "bytes 0-2/0",
                "X-Content-SHA256": hashlib.sha256(b"abc").hexdigest(),
            }
        )
        assert (
            client.put(
                upload.url, content=b"abc", headers=malformed
            ).status_code
            == 422
        )

        invalid_digest = _headers(upload)
        invalid_digest.update(
            {"Content-Range": "bytes 0-2/6", "X-Content-SHA256": "bad"}
        )
        assert (
            client.put(
                upload.url, content=b"abc", headers=invalid_digest
            ).status_code
            == 422
        )

        not_found_url = "/remote/transfer/" + "q" * 24
        assert (
            client.head(not_found_url, headers=_headers(upload)).status_code
            == 404
        )

        snapshot = store._spool_path(upload.transfer_id)
        snapshot.write_bytes(payload)
        metadata = store._load(upload.transfer_id)
        metadata["offset"] = len(payload)
        metadata["state"] = "ready"
        store._save(metadata)
        unsatisfied = _headers(download)
        unsatisfied["Range"] = "bytes=99-"
        assert client.get(download.url, headers=unsatisfied).status_code == 422


def test_private_chunk_reader_iterator_and_local_transaction_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRequest:
        def __init__(self, chunks: list[bytes]):
            self.chunks = chunks

        async def stream(self):
            for chunk in self.chunks:
                yield chunk

    temp = get_settings().remote_transfer_dir / "reader.chunk"
    temp.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(TransferGatewayError, match="exceeds"):
        asyncio.run(
            gateway_module._read_chunk_to_private_file(
                cast(Any, FakeRequest([b"abc", b"d"])),
                temp,
                3,
            )
        )
    assert not temp.exists()
    with pytest.raises(TransferGatewayError, match="does not match"):
        asyncio.run(
            gateway_module._read_chunk_to_private_file(
                cast(Any, FakeRequest([b"ab"])),
                temp,
                3,
            )
        )
    assert not temp.exists()

    released: list[tuple[str, str]] = []
    fake_store = type(
        "FakeStore",
        (),
        {
            "release_claim": lambda _self, transfer_id, claim: released.append(
                (transfer_id, claim)
            )
        },
    )()
    short_path = get_settings().remote_transfer_dir / "short.spool"
    short_path.write_bytes(b"x")
    with gateway_module._open_transfer_source(short_path) as handle:
        short_identity = gateway_module._spool_handle_identity(handle)
    short_obj = gateway_module.TransferObject(
        transfer_id="t" * 24,
        path=short_path,
        expected_bytes=2,
        expected_sha256=hashlib.sha256(b"xx").hexdigest(),
        offset=1,
        state="ready",
        identity_a=short_identity[0],
        identity_b=short_identity[1],
        identity_c=short_identity[2],
    )
    iterator = gateway_module._download_iterator(
        cast(Any, fake_store),
        "t" * 24,
        "c" * 24,
        short_obj,
        0,
        2,
    )
    assert next(iterator) == b"x"
    with pytest.raises(TransferGatewayError, match="ended unexpectedly"):
        next(iterator)
    assert released == [("t" * 24, "c" * 24)]

    payload = b"local-transaction"
    source = get_settings().remote_transfer_dir / "local-ready.spool"
    source.write_bytes(payload)
    with gateway_module._open_transfer_source(source) as handle:
        source_identity = gateway_module._spool_handle_identity(handle)
    obj = gateway_module.TransferObject(
        transfer_id="r" * 24,
        path=source,
        expected_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        offset=len(payload),
        state="ready",
        identity_a=source_identity[0],
        identity_b=source_identity[1],
        identity_c=source_identity[2],
    )
    from local_shell_mcp.ops import transfer as transfer_module

    real_abort = transfer_module.transfer_abort_write
    aborted: list[str] = []

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated local write failure")

    def record_abort(path, transfer_id, *, session_id=None):
        aborted.append(transfer_id)
        return real_abort(path, transfer_id, session_id=session_id)

    monkeypatch.setattr(transfer_module, "transfer_write_bytes", fail_write)
    monkeypatch.setattr(transfer_module, "transfer_abort_write", record_abort)
    with pytest.raises(OSError, match="simulated"):
        asyncio.run(
            gateway_module.copy_spool_to_local_transaction(
                obj,
                destination_path="local-failure.bin",
                destination_session_id=None,
                overwrite=True,
                chunk_size=4,
            )
        )
    assert aborted == [obj.transfer_id]
