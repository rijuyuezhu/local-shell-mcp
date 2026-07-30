"""Source-only worker client for private resumable HTTP transfers."""

import hashlib
import http.client
import json
import os
import re
import time
from typing import Any, BinaryIO, Literal
from urllib.parse import SplitResult, urlsplit

from local_shell_mcp.ops.transfer import (
    _open_transfer_source,
    _resolve_transfer_path,
    _stable_source_identity,
    transfer_abort_write,
    transfer_begin_write,
    transfer_finish_write,
    transfer_write_bytes,
)

_TRANSFER_PATH_RE = re.compile(r"^/remote/transfer/[A-Za-z0-9_-]{24,80}$")
_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_MAX_ERROR_BYTES = 4096
_DIRECTION_HEADER = "X-Local-Shell-MCP-Transfer-Direction"
_WORKER_HEADER = "X-Local-Shell-MCP-Worker"
_DIGEST_HEADER = "X-Content-SHA256"


class WorkerHTTPTransferError(RuntimeError):
    """Stable worker-side failure without credentials or private URLs."""


def _validate_url(url: str, controller_url: str) -> SplitResult:
    target = urlsplit(url)
    controller = urlsplit(controller_url)
    if target.scheme not in {"http", "https"}:
        raise WorkerHTTPTransferError("transfer URL scheme is unsupported")
    if target.scheme != controller.scheme or target.netloc != controller.netloc:
        raise WorkerHTTPTransferError("transfer URL origin mismatch")
    if target.username or target.password or target.query or target.fragment:
        raise WorkerHTTPTransferError(
            "transfer URL contains forbidden components"
        )
    if not _TRANSFER_PATH_RE.fullmatch(target.path):
        raise WorkerHTTPTransferError("transfer URL path is invalid")
    return target


def _connection(
    target: SplitResult, timeout_s: float
) -> http.client.HTTPConnection:
    host = target.hostname
    if not host:
        raise WorkerHTTPTransferError("transfer URL host is missing")
    port = target.port
    if target.scheme == "https":
        return http.client.HTTPSConnection(host, port=port, timeout=timeout_s)
    return http.client.HTTPConnection(host, port=port, timeout=timeout_s)


def _headers(
    *,
    authorization: str,
    worker: str,
    direction: Literal["upload", "download"],
) -> dict[str, str]:
    if not authorization or "\r" in authorization or "\n" in authorization:
        raise WorkerHTTPTransferError("transfer authorization is invalid")
    if not worker or "\r" in worker or "\n" in worker:
        raise WorkerHTTPTransferError("worker identity is invalid")
    return {
        "Authorization": authorization,
        _WORKER_HEADER: worker,
        _DIRECTION_HEADER: direction,
        "Cache-Control": "no-store",
    }


def _read_error(response: http.client.HTTPResponse) -> str:
    payload = response.read(_MAX_ERROR_BYTES + 1)[:_MAX_ERROR_BYTES]
    try:
        decoded = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return f"HTTP {response.status}"
    if isinstance(decoded, dict):
        detail = decoded.get("detail")
        if isinstance(detail, str) and detail:
            return f"HTTP {response.status}: {detail[:512]}"
    return f"HTTP {response.status}"


def _request_status(
    target: SplitResult,
    *,
    authorization: str,
    worker: str,
    direction: Literal["upload", "download"],
    timeout_s: float,
) -> dict[str, Any]:
    connection = _connection(target, timeout_s)
    try:
        connection.request(
            "HEAD",
            target.path,
            headers=_headers(
                authorization=authorization,
                worker=worker,
                direction=direction,
            ),
        )
        response = connection.getresponse()
        if response.status != 200:
            raise WorkerHTTPTransferError(_read_error(response))
        response.read()
        try:
            return {
                "offset": int(response.getheader("X-Transfer-Offset") or "0"),
                "state": response.getheader("X-Transfer-State") or "",
                "expected_bytes": int(
                    response.getheader("X-Transfer-Expected-Bytes") or "0"
                ),
                "expected_sha256": response.getheader(
                    "X-Transfer-Expected-SHA256"
                )
                or "",
            }
        except ValueError as exc:
            raise WorkerHTTPTransferError(
                "transfer status headers are invalid"
            ) from exc
    finally:
        connection.close()


def _hash_open_source(handle: BinaryIO, chunk_size: int) -> str:
    digest = hashlib.sha256()
    handle.seek(0)
    while chunk := handle.read(chunk_size):
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


def upload_file(
    *,
    path: str,
    session_id: str | None,
    url: str,
    controller_url: str,
    authorization: str,
    worker: str,
    expected_bytes: int,
    expected_sha256: str,
    chunk_size: int,
    timeout_s: float,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Push one immutable worker file with status-based retry and resume."""
    target = _validate_url(url, controller_url)
    source = _resolve_transfer_path(
        path,
        must_exist=True,
        session_id=session_id,
        workdir=workdir,
        allow_temp=True,
    )
    chunks = 0
    retries = 0
    with _open_transfer_source(source) as handle:
        initial = os.fstat(handle.fileno())
        size = int(initial.st_size)
        digest = _hash_open_source(handle, chunk_size)
        if size != int(expected_bytes) or digest != expected_sha256:
            raise WorkerHTTPTransferError("source size or digest mismatch")
        status = _request_status(
            target,
            authorization=authorization,
            worker=worker,
            direction="upload",
            timeout_s=timeout_s,
        )
        offset = int(status["offset"])
        resumed_bytes = offset
        if offset < 0 or offset > size:
            raise WorkerHTTPTransferError("controller resume offset is invalid")
        handle.seek(offset)
        while offset < size:
            chunk = handle.read(min(chunk_size, size - offset))
            if not chunk:
                raise WorkerHTTPTransferError(
                    "source ended before expected size"
                )
            chunk_digest = hashlib.sha256(chunk).hexdigest()
            headers = _headers(
                authorization=authorization,
                worker=worker,
                direction="upload",
            )
            headers.update(
                {
                    "Content-Length": str(len(chunk)),
                    "Content-Type": "application/octet-stream",
                    "Content-Range": (
                        f"bytes {offset}-{offset + len(chunk) - 1}/{size}"
                    ),
                    _DIGEST_HEADER: chunk_digest,
                }
            )
            try:
                connection = _connection(target, timeout_s)
                try:
                    connection.request(
                        "PUT", target.path, body=chunk, headers=headers
                    )
                    response = connection.getresponse()
                    if response.status != 200:
                        raise WorkerHTTPTransferError(_read_error(response))
                    payload = response.read(_MAX_ERROR_BYTES)
                    decoded = json.loads(payload.decode("utf-8"))
                    next_offset = int(decoded["offset"])
                finally:
                    connection.close()
            except (
                OSError,
                TimeoutError,
                http.client.HTTPException,
                json.JSONDecodeError,
                KeyError,
                ValueError,
            ):
                retries += 1
                if retries > 3:
                    raise WorkerHTTPTransferError(
                        "upload retry limit exceeded"
                    ) from None
                time.sleep(min(0.1 * (2**retries), 1.0))
                status = _request_status(
                    target,
                    authorization=authorization,
                    worker=worker,
                    direction="upload",
                    timeout_s=timeout_s,
                )
                next_offset = int(status["offset"])
            if next_offset not in {offset, offset + len(chunk)}:
                raise WorkerHTTPTransferError(
                    "controller returned invalid upload offset"
                )
            if next_offset == offset:
                handle.seek(offset)
                continue
            offset = next_offset
            handle.seek(offset)
            chunks += 1
        final = os.fstat(handle.fileno())
        if _stable_source_identity(initial) != _stable_source_identity(final):
            raise WorkerHTTPTransferError("source changed during upload")
    final_status = _request_status(
        target,
        authorization=authorization,
        worker=worker,
        direction="upload",
        timeout_s=timeout_s,
    )
    if int(final_status["offset"]) != size or final_status["state"] != "ready":
        raise WorkerHTTPTransferError(
            "controller did not commit uploaded object"
        )
    return {
        "bytes": size,
        "sha256": digest,
        "chunks": chunks,
        "chunk_size": chunk_size,
        "resumed_bytes": resumed_bytes,
        "completed": True,
    }


def _download_chunk(
    target: SplitResult,
    *,
    authorization: str,
    worker: str,
    start: int,
    expected_bytes: int,
    chunk_size: int,
    timeout_s: float,
) -> bytes:
    end = min(expected_bytes - 1, start + chunk_size - 1)
    headers = _headers(
        authorization=authorization, worker=worker, direction="download"
    )
    headers["Range"] = f"bytes={start}-{end}"
    connection = _connection(target, timeout_s)
    try:
        connection.request("GET", target.path, headers=headers)
        response = connection.getresponse()
        if response.status != 206:
            raise WorkerHTTPTransferError(_read_error(response))
        content_range = response.getheader("Content-Range") or ""
        match = _CONTENT_RANGE_RE.fullmatch(content_range)
        if match is None:
            raise WorkerHTTPTransferError("download Content-Range is invalid")
        actual_start, actual_end, total = (
            int(value) for value in match.groups()
        )
        if (
            actual_start != start
            or actual_end != end
            or total != expected_bytes
        ):
            raise WorkerHTTPTransferError("download Content-Range mismatch")
        expected_length = end - start + 1
        body = response.read(expected_length + 1)
        if len(body) != expected_length:
            raise WorkerHTTPTransferError("download body length mismatch")
        return body
    finally:
        connection.close()


def download_file(
    *,
    path: str,
    session_id: str | None,
    url: str,
    controller_url: str,
    authorization: str,
    worker: str,
    transfer_id: str,
    expected_bytes: int,
    expected_sha256: str,
    overwrite: bool,
    chunk_size: int,
    timeout_s: float,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Pull one immutable controller object into a resumable local transaction."""
    target = _validate_url(url, controller_url)
    status = _request_status(
        target,
        authorization=authorization,
        worker=worker,
        direction="download",
        timeout_s=timeout_s,
    )
    if status["state"] != "ready":
        raise WorkerHTTPTransferError("download object is not ready")
    if int(status["expected_bytes"]) != int(expected_bytes):
        raise WorkerHTTPTransferError("download size metadata mismatch")
    if status["expected_sha256"] != expected_sha256:
        raise WorkerHTTPTransferError("download digest metadata mismatch")
    begin = transfer_begin_write(
        path,
        overwrite,
        expected_bytes,
        transfer_id,
        session_id=session_id,
        workdir=workdir,
    )
    offset = int(begin.offset)
    resumed_bytes = offset
    chunks = 0
    try:
        while offset < expected_bytes:
            retries = 0
            while True:
                try:
                    chunk = _download_chunk(
                        target,
                        authorization=authorization,
                        worker=worker,
                        start=offset,
                        expected_bytes=expected_bytes,
                        chunk_size=chunk_size,
                        timeout_s=timeout_s,
                    )
                    break
                except OSError, TimeoutError, http.client.HTTPException:
                    retries += 1
                    if retries > 3:
                        raise WorkerHTTPTransferError(
                            "download retry limit exceeded"
                        ) from None
                    time.sleep(min(0.1 * (2**retries), 1.0))
            transfer_write_bytes(
                path,
                transfer_id,
                offset,
                chunk,
                hashlib.sha256(chunk).hexdigest(),
                session_id=session_id,
                workdir=workdir,
            )
            offset += len(chunk)
            chunks += 1
        finish = transfer_finish_write(
            path,
            transfer_id,
            expected_bytes,
            expected_sha256,
            session_id=session_id,
            workdir=workdir,
        )
    except BaseException:
        # Keep a valid partial transaction for restart/retry. Explicit cancellation
        # and controller abort cleanup are handled by the transfer TTL/pruner.
        raise
    return {
        "path": finish.path,
        "bytes": finish.bytes,
        "sha256": finish.sha256,
        "chunks": chunks,
        "chunk_size": chunk_size,
        "resumed_bytes": resumed_bytes,
        "completed": finish.completed,
    }


def abort_download(
    *,
    path: str,
    session_id: str | None,
    transfer_id: str,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Explicitly remove a worker-side partial destination transaction."""
    return transfer_abort_write(
        path, transfer_id, session_id=session_id, workdir=workdir
    ).model_dump(mode="json")
