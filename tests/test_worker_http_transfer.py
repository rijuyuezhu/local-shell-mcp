import hashlib
import json
import socket
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit

import pytest
import uvicorn
from starlette.applications import Starlette

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.transfer import (
    transfer_begin_write,
    transfer_write_bytes,
)
from local_shell_mcp.remote.transfer_gateway import (
    TransferGatewayStore,
    build_transfer_gateway_router,
)
from local_shell_mcp.remote_worker import http_transfer
from local_shell_mcp.remote_worker.http_transfer import WorkerHTTPTransferError
from local_shell_mcp.utils.private_files import write_private_bytes


@contextmanager
def _gateway_server(monkeypatch: pytest.MonkeyPatch) -> Generator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    base_url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", base_url)
    clear_settings_cache()
    app = Starlette(routes=list(build_transfer_gateway_router()))
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", lifespan="off", access_log=False)
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while (
        not server.started and thread.is_alive() and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        raise RuntimeError("test gateway did not start")
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        clear_settings_cache()


def _prepare_partial_upload(
    store: TransferGatewayStore, transfer_id: str, payload: bytes
) -> None:
    _data, claim = store.begin_claim(transfer_id, "upload")
    chunk_path = store._chunk_path(transfer_id, claim)
    write_private_bytes(chunk_path, payload, exclusive=True)
    try:
        store.commit_chunk(
            transfer_id,
            claim,
            chunk_path,
            0,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    finally:
        chunk_path.unlink(missing_ok=True)


def test_worker_upload_and_download_resume_over_real_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _gateway_server(monkeypatch) as base_url:
        settings = get_settings()
        payload = b"worker-http-resume-payload"
        digest = hashlib.sha256(payload).hexdigest()
        source = settings.workspace_root / "worker-source.bin"
        source.write_bytes(payload)
        store = TransferGatewayStore(settings)
        obj, upload, download = store.prepare(
            expected_bytes=len(payload),
            expected_sha256=digest,
            upload_worker="worker-upload",
            download_worker="worker-download",
            source_session_id="source-session",
            destination_session_id="destination-session",
            resume_key="worker-resume",
        )
        assert upload is not None
        assert download is not None
        _prepare_partial_upload(store, obj.transfer_id, payload[:5])

        upload_result = http_transfer.upload_file(
            path="worker-source.bin",
            session_id=None,
            url=upload.url,
            controller_url=base_url,
            authorization=upload.authorization,
            worker=upload.worker,
            expected_bytes=len(payload),
            expected_sha256=digest,
            chunk_size=4,
            timeout_s=5,
        )
        assert upload_result["resumed_bytes"] == 5
        assert upload_result["completed"] is True
        assert store.object(obj.transfer_id).path.read_bytes() == payload

        begin = transfer_begin_write(
            "worker-destination.bin", True, len(payload), obj.transfer_id
        )
        transfer_write_bytes(
            "worker-destination.bin", begin.transfer_id, 0, payload[:3]
        )
        download_result = http_transfer.download_file(
            path="worker-destination.bin",
            session_id=None,
            url=download.url,
            controller_url=base_url,
            authorization=download.authorization,
            worker=download.worker,
            transfer_id=obj.transfer_id,
            expected_bytes=len(payload),
            expected_sha256=digest,
            overwrite=True,
            chunk_size=5,
            timeout_s=5,
        )
        assert download_result["resumed_bytes"] == 3
        assert download_result["completed"] is True
        assert (
            settings.workspace_root / "worker-destination.bin"
        ).read_bytes() == payload

        abort_id = "a" * 32
        transfer_begin_write("abort-destination.bin", True, 1, abort_id)
        aborted = http_transfer.abort_download(
            path="abort-destination.bin", session_id=None, transfer_id=abort_id
        )
        assert aborted["deleted"] is True


def test_worker_rejects_source_and_download_metadata_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _gateway_server(monkeypatch) as base_url:
        settings = get_settings()
        payload = b"metadata-payload"
        digest = hashlib.sha256(payload).hexdigest()
        (settings.workspace_root / "source.bin").write_bytes(payload)
        store = TransferGatewayStore(settings)
        obj, upload, download = store.prepare(
            expected_bytes=len(payload),
            expected_sha256=digest,
            upload_worker="source-worker",
            download_worker="destination-worker",
            source_session_id="source-session",
            destination_session_id="destination-session",
        )
        assert upload is not None
        assert download is not None
        with pytest.raises(
            WorkerHTTPTransferError, match="source size or digest"
        ):
            http_transfer.upload_file(
                path="source.bin",
                session_id=None,
                url=upload.url,
                controller_url=base_url,
                authorization=upload.authorization,
                worker=upload.worker,
                expected_bytes=len(payload),
                expected_sha256="0" * 64,
                chunk_size=4,
                timeout_s=5,
            )
        with pytest.raises(WorkerHTTPTransferError, match="not ready"):
            http_transfer.download_file(
                path="destination.bin",
                session_id=None,
                url=download.url,
                controller_url=base_url,
                authorization=download.authorization,
                worker=download.worker,
                transfer_id=obj.transfer_id,
                expected_bytes=len(payload),
                expected_sha256=digest,
                overwrite=True,
                chunk_size=4,
                timeout_s=5,
            )

        _prepare_partial_upload(store, obj.transfer_id, payload)
        with pytest.raises(WorkerHTTPTransferError, match="size metadata"):
            http_transfer.download_file(
                path="destination.bin",
                session_id=None,
                url=download.url,
                controller_url=base_url,
                authorization=download.authorization,
                worker=download.worker,
                transfer_id=obj.transfer_id,
                expected_bytes=len(payload) + 1,
                expected_sha256=digest,
                overwrite=True,
                chunk_size=4,
                timeout_s=5,
            )
        with pytest.raises(WorkerHTTPTransferError, match="digest metadata"):
            http_transfer.download_file(
                path="destination.bin",
                session_id=None,
                url=download.url,
                controller_url=base_url,
                authorization=download.authorization,
                worker=download.worker,
                transfer_id=obj.transfer_id,
                expected_bytes=len(payload),
                expected_sha256="f" * 64,
                overwrite=True,
                chunk_size=4,
                timeout_s=5,
            )


def test_worker_header_error_and_protocol_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(WorkerHTTPTransferError, match="authorization"):
        http_transfer._headers(
            authorization="bad\nheader", worker="worker", direction="upload"
        )
    with pytest.raises(WorkerHTTPTransferError, match="worker identity"):
        http_transfer._headers(
            authorization="Transfer token",
            worker="bad\rworker",
            direction="download",
        )
    with pytest.raises(WorkerHTTPTransferError, match="host is missing"):
        http_transfer._connection(
            SplitResult("http", "", "/remote/transfer/" + "a" * 24, "", ""), 1
        )
    https_connection = http_transfer._connection(
        urlsplit("https://example.test/remote/transfer/" + "a" * 24), 1
    )
    assert https_connection.__class__.__name__ == "HTTPSConnection"
    https_connection.close()

    class FakeResponse:
        def __init__(
            self,
            status: int,
            body: bytes,
            headers: dict[str, str] | None = None,
        ):
            self.status = status
            self._body = body
            self._headers = headers or {}

        def read(self, _amount: int | None = None) -> bytes:
            return self._body

        def getheader(self, name: str) -> str | None:
            return self._headers.get(name)

    assert (
        http_transfer._read_error(cast(Any, FakeResponse(500, b"not-json")))
        == "HTTP 500"
    )
    assert (
        http_transfer._read_error(cast(Any, FakeResponse(422, b"[]")))
        == "HTTP 422"
    )
    detail = json.dumps({"detail": "x" * 700}).encode()
    assert http_transfer._read_error(
        cast(Any, FakeResponse(409, detail))
    ).startswith("HTTP 409: " + "x" * 100)

    invalid_status = FakeResponse(
        200,
        b"",
        {
            "X-Transfer-Offset": "not-an-int",
            "X-Transfer-State": "ready",
        },
    )
    fake_connection = SimpleNamespace(
        request=lambda *_args, **_kwargs: None,
        getresponse=lambda: invalid_status,
        close=lambda: None,
    )
    monkeypatch.setattr(
        http_transfer, "_connection", lambda _target, _timeout: fake_connection
    )
    with pytest.raises(WorkerHTTPTransferError, match="status headers"):
        http_transfer._request_status(
            urlsplit("http://example.test/remote/transfer/" + "a" * 24),
            authorization="Transfer token",
            worker="worker",
            direction="upload",
            timeout_s=1,
        )


def test_worker_upload_retry_offsets_and_final_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    payload = b"retry-payload"
    digest = hashlib.sha256(payload).hexdigest()
    (settings.workspace_root / "retry-source.bin").write_bytes(payload)
    target_url = "http://example.test/remote/transfer/" + "b" * 24

    with pytest.raises(WorkerHTTPTransferError, match="resume offset"):
        monkeypatch.setattr(
            http_transfer,
            "_request_status",
            lambda *_args, **_kwargs: {
                "offset": len(payload) + 1,
                "state": "uploading",
            },
        )
        http_transfer.upload_file(
            path="retry-source.bin",
            session_id=None,
            url=target_url,
            controller_url="http://example.test",
            authorization="Transfer token",
            worker="worker",
            expected_bytes=len(payload),
            expected_sha256=digest,
            chunk_size=len(payload),
            timeout_s=1,
        )

    class FakeResponse:
        status = 200

        def __init__(self, offset: int):
            self.offset = offset

        def read(self, _amount: int | None = None) -> bytes:
            return json.dumps({"offset": self.offset}).encode()

    class FakeConnection:
        def __init__(
            self, response: FakeResponse | None = None, *, fail: bool = False
        ):
            self.response = response
            self.fail = fail

        def request(self, *_args, **_kwargs) -> None:
            if self.fail:
                raise OSError("transient")

        def getresponse(self) -> FakeResponse:
            assert self.response is not None
            return self.response

        def close(self) -> None:
            return None

    statuses = iter(
        [
            {"offset": 0, "state": "uploading"},
            {"offset": 0, "state": "uploading"},
            {"offset": len(payload), "state": "ready"},
        ]
    )
    monkeypatch.setattr(
        http_transfer, "_request_status", lambda *_a, **_k: next(statuses)
    )
    connections = iter(
        [FakeConnection(fail=True), FakeConnection(FakeResponse(len(payload)))]
    )
    monkeypatch.setattr(
        http_transfer, "_connection", lambda *_a, **_k: next(connections)
    )
    monkeypatch.setattr(http_transfer.time, "sleep", lambda _delay: None)
    result = http_transfer.upload_file(
        path="retry-source.bin",
        session_id=None,
        url=target_url,
        controller_url="http://example.test",
        authorization="Transfer token",
        worker="worker",
        expected_bytes=len(payload),
        expected_sha256=digest,
        chunk_size=len(payload),
        timeout_s=1,
    )
    assert result["completed"] is True

    monkeypatch.setattr(
        http_transfer,
        "_request_status",
        lambda *_a, **_k: {"offset": 0, "state": "uploading"},
    )
    monkeypatch.setattr(
        http_transfer,
        "_connection",
        lambda *_a, **_k: FakeConnection(FakeResponse(len(payload) + 5)),
    )
    with pytest.raises(WorkerHTTPTransferError, match="invalid upload offset"):
        http_transfer.upload_file(
            path="retry-source.bin",
            session_id=None,
            url=target_url,
            controller_url="http://example.test",
            authorization="Transfer token",
            worker="worker",
            expected_bytes=len(payload),
            expected_sha256=digest,
            chunk_size=len(payload),
            timeout_s=1,
        )

    statuses = iter(
        [
            {"offset": 0, "state": "uploading"},
            {"offset": len(payload), "state": "uploading"},
        ]
    )
    monkeypatch.setattr(
        http_transfer, "_request_status", lambda *_a, **_k: next(statuses)
    )
    monkeypatch.setattr(
        http_transfer,
        "_connection",
        lambda *_a, **_k: FakeConnection(FakeResponse(len(payload))),
    )
    with pytest.raises(WorkerHTTPTransferError, match="did not commit"):
        http_transfer.upload_file(
            path="retry-source.bin",
            session_id=None,
            url=target_url,
            controller_url="http://example.test",
            authorization="Transfer token",
            worker="worker",
            expected_bytes=len(payload),
            expected_sha256=digest,
            chunk_size=len(payload),
            timeout_s=1,
        )


def test_worker_download_protocol_and_retry_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = urlsplit("http://example.test/remote/transfer/" + "c" * 24)

    class FakeResponse:
        def __init__(self, status: int, body: bytes, headers: dict[str, str]):
            self.status = status
            self.body = body
            self.headers = headers

        def read(self, amount: int | None = None) -> bytes:
            return self.body if amount is None else self.body[:amount]

        def getheader(self, name: str) -> str | None:
            return self.headers.get(name)

    class FakeConnection:
        def __init__(self, response: FakeResponse):
            self.response = response

        def request(self, *_args, **_kwargs) -> None:
            return None

        def getresponse(self) -> FakeResponse:
            return self.response

        def close(self) -> None:
            return None

    cases = [
        (FakeResponse(500, b"{}", {}), "HTTP 500"),
        (
            FakeResponse(206, b"abc", {"Content-Range": "bad"}),
            "Content-Range is invalid",
        ),
        (
            FakeResponse(206, b"abc", {"Content-Range": "bytes 1-3/3"}),
            "Content-Range mismatch",
        ),
        (
            FakeResponse(206, b"ab", {"Content-Range": "bytes 0-2/3"}),
            "body length mismatch",
        ),
    ]
    for response, message in cases:
        monkeypatch.setattr(
            http_transfer,
            "_connection",
            lambda *_a, _response=response, **_k: FakeConnection(_response),
        )
        with pytest.raises(WorkerHTTPTransferError, match=message):
            http_transfer._download_chunk(
                target,
                authorization="Transfer token",
                worker="worker",
                start=0,
                expected_bytes=3,
                chunk_size=3,
                timeout_s=1,
            )

    settings = get_settings()
    payload = b"download-retry"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        http_transfer,
        "_request_status",
        lambda *_a, **_k: {
            "offset": len(payload),
            "state": "ready",
            "expected_bytes": len(payload),
            "expected_sha256": digest,
        },
    )
    attempts = iter([OSError("transient"), payload])

    def flaky_download(*_args, **_kwargs):
        value = next(attempts)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(http_transfer, "_download_chunk", flaky_download)
    monkeypatch.setattr(http_transfer.time, "sleep", lambda _delay: None)
    result = http_transfer.download_file(
        path="retry-download.bin",
        session_id=None,
        url="http://example.test/remote/transfer/" + "d" * 24,
        controller_url="http://example.test",
        authorization="Transfer token",
        worker="worker",
        transfer_id="d" * 32,
        expected_bytes=len(payload),
        expected_sha256=digest,
        overwrite=True,
        chunk_size=len(payload),
        timeout_s=1,
    )
    assert (
        settings.workspace_root / "retry-download.bin"
    ).read_bytes() == payload
    assert result["completed"] is True

    monkeypatch.setattr(
        http_transfer,
        "_download_chunk",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("always")),
    )
    with pytest.raises(WorkerHTTPTransferError, match="retry limit"):
        http_transfer.download_file(
            path="failed-download.bin",
            session_id=None,
            url="http://example.test/remote/transfer/" + "e" * 24,
            controller_url="http://example.test",
            authorization="Transfer token",
            worker="worker",
            transfer_id="e" * 32,
            expected_bytes=len(payload),
            expected_sha256=digest,
            overwrite=True,
            chunk_size=len(payload),
            timeout_s=1,
        )


def test_worker_rejects_unsupported_scheme_and_http_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(WorkerHTTPTransferError, match="scheme"):
        http_transfer._validate_url(
            "ftp://example.test/remote/transfer/" + "f" * 24,
            "ftp://example.test",
        )

    response = SimpleNamespace(
        status=401,
        read=lambda _amount=None: b'{"detail":"authorization rejected"}',
        getheader=lambda _name: None,
    )
    connection = SimpleNamespace(
        request=lambda *_a, **_k: None,
        getresponse=lambda: response,
        close=lambda: None,
    )
    monkeypatch.setattr(
        http_transfer, "_connection", lambda *_a, **_k: connection
    )
    with pytest.raises(WorkerHTTPTransferError, match="authorization rejected"):
        http_transfer._request_status(
            urlsplit("http://example.test/remote/transfer/" + "f" * 24),
            authorization="Transfer bad",
            worker="worker",
            direction="upload",
            timeout_s=1,
        )
