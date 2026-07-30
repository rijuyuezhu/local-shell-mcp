"""Private durable HTTP transfer gateway used only by ``session_copy``."""

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import BaseRoute, Route

from ..config.settings import Settings, get_settings
from ..ops.transfer import (
    _open_transfer_for_update,
    _open_transfer_source,
    _stable_source_identity,
    _transfer_handle_identity,
)
from ..utils.private_files import (
    atomic_write_private_text,
    private_file_lock,
    write_private_bytes,
)

_TRANSFER_VERSION = 1
_TRANSFER_PATH_RE = re.compile(r"^[A-Za-z0-9_-]{24,80}$")
_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")
_AUTH_SCHEME = "Transfer"
_WORKER_HEADER = "x-local-shell-mcp-worker"
_DIRECTION_HEADER = "x-local-shell-mcp-transfer-direction"
_CHUNK_DIGEST_HEADER = "x-content-sha256"
_PROCESS_NONCE = secrets.token_urlsafe(24)
_RESUME_RETENTION_S = 24 * 60 * 60


class TransferGatewayError(RuntimeError):
    """Stable internal error raised for rejected gateway operations."""


@dataclass(frozen=True)
class TransferGrant:
    """One private worker-bound gateway grant returned only to controller code."""

    transfer_id: str
    """Non-secret durable transfer object identifier."""
    url: str
    """Controller route containing no credential-bearing query data."""
    authorization: str
    """Short-lived separate capability header value."""
    worker: str
    """Registered worker identity bound to this capability."""
    direction: Literal["upload", "download"]
    """Only operation direction permitted by this capability."""
    expected_bytes: int
    """Whole-object byte count bound to the grant."""
    expected_sha256: str
    """Whole-object SHA-256 bound to the grant."""
    offset: int
    """Authoritative durable cursor when the grant was issued."""
    resumed_bytes: int
    """Validated bytes available for upload resume."""


@dataclass(frozen=True)
class TransferObject:
    """Validated controller-side view of one durable transfer object."""

    transfer_id: str
    """Non-secret durable transfer object identifier."""
    path: Path
    """Private controller spool path."""
    expected_bytes: int
    """Expected final byte count."""
    expected_sha256: str
    """Expected whole-object SHA-256."""
    offset: int
    """Validated contiguous bytes currently stored."""
    state: str
    """Durable transfer lifecycle state."""
    identity_a: int
    """First platform-native spool identity component."""
    identity_b: int
    """Second platform-native spool identity component."""
    identity_c: int
    """Latest native change/write generation bound to the current spool contents."""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _spool_handle_identity(handle: BinaryIO) -> tuple[int, int, int]:
    """Return stable file identity plus a refreshable content generation."""
    identity_a, identity_b = _transfer_handle_identity(handle)
    file_stat = os.fstat(handle.fileno())
    generation = max(int(file_stat.st_ctime_ns), int(file_stat.st_mtime_ns))
    return identity_a, identity_b, generation


class TransferGatewayStore:
    """Persist and validate private transfer metadata and disk-backed spools."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the owner-private durable transfer state directory."""
        self.settings = settings or get_settings()
        self.root = self.settings.remote_transfer_dir
        self.root.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            self.root.chmod(0o700)
        self.lock_path = self.root / "gateway.lock"

    def _metadata_path(self, transfer_id: str) -> Path:
        self._validate_transfer_id(transfer_id)
        return self.root / f"{transfer_id}.json"

    def _spool_path(self, transfer_id: str) -> Path:
        self._validate_transfer_id(transfer_id)
        return self.root / f"{transfer_id}.spool"

    @staticmethod
    def _spool_identity(data: dict[str, Any]) -> tuple[int, int, int]:
        try:
            return (
                int(data["spool_identity_a"]),
                int(data["spool_identity_b"]),
                int(data["spool_identity_c"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransferGatewayError(
                "transfer spool identity is missing"
            ) from exc

    def _open_spool(
        self, data: dict[str, Any], *, update: bool = False
    ) -> BinaryIO:
        transfer_id = str(data.get("transfer_id") or "")
        path = self._spool_path(transfer_id)
        try:
            handle = (
                _open_transfer_for_update(path)
                if update
                else _open_transfer_source(path)
            )
        except (
            FileNotFoundError,
            IsADirectoryError,
            OSError,
            ValueError,
        ) as exc:
            raise TransferGatewayError(
                "transfer spool is missing or unsafe"
            ) from exc
        expected_identity = self._spool_identity(data)
        actual_identity = _spool_handle_identity(handle)
        if actual_identity != expected_identity:
            handle.close()
            raise TransferGatewayError("transfer spool identity changed")
        return handle

    def _chunk_path(self, transfer_id: str, claim: str) -> Path:
        self._validate_transfer_id(transfer_id)
        if not _TRANSFER_PATH_RE.fullmatch(claim):
            raise TransferGatewayError("invalid transfer claim")
        return self.root / f".{transfer_id}.{claim}.chunk"

    @staticmethod
    def _validate_transfer_id(transfer_id: str) -> None:
        if not _TRANSFER_PATH_RE.fullmatch(transfer_id):
            raise TransferGatewayError("invalid transfer identifier")

    def _load(self, transfer_id: str) -> dict[str, Any]:
        path = self._metadata_path(transfer_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise TransferGatewayError("transfer not found") from None
        except (OSError, json.JSONDecodeError) as exc:
            raise TransferGatewayError(
                "transfer metadata is unreadable"
            ) from exc
        if (
            not isinstance(data, dict)
            or data.get("version") != _TRANSFER_VERSION
        ):
            raise TransferGatewayError("unsupported transfer metadata")
        if data.get("transfer_id") != transfer_id:
            raise TransferGatewayError("transfer metadata identity mismatch")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        transfer_id = str(data["transfer_id"])
        data["updated_at"] = time.time()
        atomic_write_private_text(
            self._metadata_path(transfer_id),
            _json_bytes(data).decode("utf-8"),
        )

    def _iter_metadata(self) -> Iterator[dict[str, Any]]:
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except OSError, json.JSONDecodeError:
                continue
            if (
                isinstance(data, dict)
                and data.get("version") == _TRANSFER_VERSION
            ):
                yield data

    def _cleanup_expired_locked(self, now: float) -> None:
        for data in list(self._iter_metadata()):
            transfer_id = str(data.get("transfer_id") or "")
            if not _TRANSFER_PATH_RE.fullmatch(transfer_id):
                continue
            expires_at = float(data.get("expires_at") or 0)
            state = str(data.get("state") or "")
            if expires_at > now and state not in {
                "aborted",
                "failed",
                "consumed",
            }:
                continue
            self._delete_locked(transfer_id)
        for path in self.root.glob(".*.chunk"):
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < now - max(
                    60, self.settings.remote_http_transfer_ticket_ttl_s
                ):
                    path.unlink()

    def _delete_locked(self, transfer_id: str) -> None:
        self._metadata_path(transfer_id).unlink(missing_ok=True)
        self._spool_path(transfer_id).unlink(missing_ok=True)
        for path in self.root.glob(f".{transfer_id}.*.chunk"):
            path.unlink(missing_ok=True)

    def _reserve_locked(self, expected_bytes: int) -> None:
        active = 0
        reserved = 0
        for data in self._iter_metadata():
            state = str(data.get("state") or "")
            if state in {"aborted", "failed", "consumed"}:
                continue
            active += 1
            reserved += int(data.get("expected_bytes") or 0)
        if active >= self.settings.remote_http_transfer_max_active:
            raise TransferGatewayError("maximum active transfers reached")
        if (
            reserved + expected_bytes
            > self.settings.remote_http_transfer_max_spool_bytes
        ):
            raise TransferGatewayError("transfer spool quota exceeded")

    def _new_transfer_id(self, resume_key: str | None) -> str:
        if resume_key:
            digest = hashlib.sha256(resume_key.encode("utf-8")).digest()
            return (
                secrets.token_urlsafe(6)
                + hashlib.sha256(digest).hexdigest()[:32]
            )
        return secrets.token_urlsafe(24)

    def _find_resume_locked(
        self, resume_key_hash: str
    ) -> dict[str, Any] | None:
        for data in self._iter_metadata():
            if hmac.compare_digest(
                str(data.get("resume_key_hash") or ""), resume_key_hash
            ):
                return data
        return None

    def prepare(
        self,
        *,
        expected_bytes: int,
        expected_sha256: str,
        upload_worker: str | None,
        download_worker: str | None,
        source_session_id: str,
        destination_session_id: str,
        resume_key: str | None = None,
        snapshot_path: Path | None = None,
    ) -> tuple[TransferObject, TransferGrant | None, TransferGrant | None]:
        """Create or resume one durable object and rotate worker capabilities."""
        expected = int(expected_bytes)
        digest = str(expected_sha256).lower()
        if expected < 0:
            raise TransferGatewayError(
                "expected transfer size must be non-negative"
            )
        if expected > self.settings.remote_http_transfer_max_spool_bytes:
            raise TransferGatewayError(
                "transfer exceeds controller spool limit"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise TransferGatewayError("expected transfer digest is invalid")
        now = time.time()
        resume_hash = _token_hash(resume_key) if resume_key else ""
        with private_file_lock(self.lock_path):
            self._cleanup_expired_locked(now)
            data = (
                self._find_resume_locked(resume_hash) if resume_hash else None
            )
            if data is not None:
                if (
                    int(data.get("expected_bytes") or -1) != expected
                    or str(data.get("expected_sha256") or "") != digest
                    or str(data.get("source_session_id") or "")
                    != source_session_id
                    or str(data.get("destination_session_id") or "")
                    != destination_session_id
                ):
                    raise TransferGatewayError(
                        "resume metadata does not match copy"
                    )
                transfer_id = str(data["transfer_id"])
                spool = self._spool_path(transfer_id)
                offset = int(data.get("offset") or 0)
                with self._open_spool(data, update=True) as handle:
                    if os.fstat(handle.fileno()).st_size != offset:
                        raise TransferGatewayError(
                            "transfer spool size changed"
                        )
            else:
                self._reserve_locked(expected)
                transfer_id = self._new_transfer_id(resume_key)
                while self._metadata_path(transfer_id).exists():
                    transfer_id = secrets.token_urlsafe(24)
                spool = self._spool_path(transfer_id)
                if snapshot_path is None:
                    write_private_bytes(spool, b"", exclusive=True)
                    offset = 0
                    state = "uploading"
                else:
                    self._copy_snapshot(snapshot_path, spool, expected, digest)
                    offset = expected
                    state = "ready"
                with _open_transfer_for_update(spool) as handle:
                    spool_identity = _spool_handle_identity(handle)
                    if os.fstat(handle.fileno()).st_size != offset:
                        spool.unlink(missing_ok=True)
                        raise TransferGatewayError(
                            "transfer spool size changed"
                        )
                data = {
                    "version": _TRANSFER_VERSION,
                    "transfer_id": transfer_id,
                    "resume_key_hash": resume_hash,
                    "source_session_id": source_session_id,
                    "destination_session_id": destination_session_id,
                    "expected_bytes": expected,
                    "expected_sha256": digest,
                    "offset": offset,
                    "state": state,
                    "spool_identity_a": spool_identity[0],
                    "spool_identity_b": spool_identity[1],
                    "spool_identity_c": spool_identity[2],
                    "created_at": now,
                    "updated_at": now,
                    "expires_at": now
                    + self.settings.remote_http_transfer_ticket_ttl_s,
                    "claim": None,
                    "last_chunk": None,
                }
            upload_token = secrets.token_urlsafe(32) if upload_worker else None
            download_token = (
                secrets.token_urlsafe(32) if download_worker else None
            )
            data.update(
                {
                    "upload_worker": upload_worker,
                    "upload_token_hash": (
                        _token_hash(upload_token) if upload_token else None
                    ),
                    "download_worker": download_worker,
                    "download_token_hash": (
                        _token_hash(download_token) if download_token else None
                    ),
                    "expires_at": now
                    + self.settings.remote_http_transfer_ticket_ttl_s,
                    "claim": None,
                }
            )
            self._save(data)
        obj = TransferObject(
            transfer_id=transfer_id,
            path=spool,
            expected_bytes=expected,
            expected_sha256=digest,
            offset=int(data.get("offset") or 0),
            state=str(data.get("state") or ""),
            identity_a=int(data["spool_identity_a"]),
            identity_b=int(data["spool_identity_b"]),
            identity_c=int(data["spool_identity_c"]),
        )
        return (
            obj,
            self._grant(data, upload_token, "upload") if upload_token else None,
            self._grant(data, download_token, "download")
            if download_token
            else None,
        )

    def _grant(
        self,
        data: dict[str, Any],
        token: str,
        direction: Literal["upload", "download"],
    ) -> TransferGrant:
        worker = str(data[f"{direction}_worker"])
        offset = int(data.get("offset") or 0)
        return TransferGrant(
            transfer_id=str(data["transfer_id"]),
            url=(
                f"{self.settings.resolved_base_url}/remote/transfer/"
                f"{data['transfer_id']}"
            ),
            authorization=f"{_AUTH_SCHEME} {token}",
            worker=worker,
            direction=direction,
            expected_bytes=int(data["expected_bytes"]),
            expected_sha256=str(data["expected_sha256"]),
            offset=offset,
            resumed_bytes=offset if direction == "upload" else 0,
        )

    @staticmethod
    def _copy_snapshot(
        source: Path,
        destination: Path,
        expected_bytes: int,
        expected_sha256: str,
    ) -> None:
        digest = hashlib.sha256()
        copied = 0
        try:
            source_handle = _open_transfer_source(source)
        except (
            FileNotFoundError,
            IsADirectoryError,
            OSError,
            ValueError,
        ) as exc:
            raise TransferGatewayError(
                "snapshot source is missing or unsafe"
            ) from exc
        try:
            with source_handle as src:
                before = os.fstat(src.fileno())
                out_descriptor = os.open(
                    destination,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | int(getattr(os, "O_BINARY", 0)),
                    0o600,
                )
                with os.fdopen(out_descriptor, "wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                after = os.fstat(src.fileno())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if _stable_source_identity(before) != _stable_source_identity(after):
            destination.unlink(missing_ok=True)
            raise TransferGatewayError("snapshot source changed during copy")
        if copied != expected_bytes or digest.hexdigest() != expected_sha256:
            destination.unlink(missing_ok=True)
            raise TransferGatewayError("snapshot size or digest mismatch")

    def authenticate(
        self,
        transfer_id: str,
        authorization: str | None,
        worker: str | None,
        direction: Literal["upload", "download"],
    ) -> dict[str, Any]:
        """Validate one separate capability header and its worker binding."""
        if not authorization or not authorization.startswith(
            f"{_AUTH_SCHEME} "
        ):
            raise TransferGatewayError("transfer authorization required")
        token = authorization.removeprefix(f"{_AUTH_SCHEME} ").strip()
        if not token or not worker:
            raise TransferGatewayError("transfer authorization required")
        with private_file_lock(self.lock_path):
            data = self._load(transfer_id)
            now = time.time()
            if float(data.get("expires_at") or 0) <= now:
                raise TransferGatewayError("transfer grant expired")
            expected_worker = str(data.get(f"{direction}_worker") or "")
            expected_hash = str(data.get(f"{direction}_token_hash") or "")
            if worker != expected_worker or not hmac.compare_digest(
                _token_hash(token), expected_hash
            ):
                raise TransferGatewayError("transfer authorization rejected")
            if str(data.get("state") or "") in {
                "aborted",
                "failed",
                "consumed",
            }:
                raise TransferGatewayError("transfer is no longer active")
            data["expires_at"] = (
                now + self.settings.remote_http_transfer_ticket_ttl_s
            )
            self._save(data)
            return data

    def begin_claim(
        self, transfer_id: str, direction: Literal["upload", "download"]
    ) -> tuple[dict[str, Any], str]:
        """Acquire one process-owned exclusive operation claim."""
        claim = secrets.token_urlsafe(24)
        with private_file_lock(self.lock_path):
            data = self._load(transfer_id)
            current = data.get("claim")
            if (
                isinstance(current, dict)
                and current.get("owner") != _PROCESS_NONCE
            ):
                current = None
                data["claim"] = None
            if current:
                raise TransferGatewayError(
                    "transfer already has an active claim"
                )
            data["claim"] = {
                "id": claim,
                "direction": direction,
                "at": time.time(),
                "owner": _PROCESS_NONCE,
            }
            self._save(data)
        return data, claim

    def release_claim(self, transfer_id: str, claim: str) -> None:
        """Release a matching active operation claim when it still exists."""
        with (
            private_file_lock(self.lock_path),
            contextlib.suppress(TransferGatewayError),
        ):
            data = self._load(transfer_id)
            current = data.get("claim")
            if isinstance(current, dict) and current.get("id") == claim:
                data["claim"] = None
                self._save(data)

    def status(self, transfer_id: str) -> dict[str, Any]:
        """Return non-secret durable status for an authorized worker poll."""
        with private_file_lock(self.lock_path):
            data = self._load(transfer_id)
            return {
                "transfer_id": transfer_id,
                "state": str(data.get("state") or ""),
                "offset": int(data.get("offset") or 0),
                "expected_bytes": int(data.get("expected_bytes") or 0),
                "expected_sha256": str(data.get("expected_sha256") or ""),
                "expires_at": float(data.get("expires_at") or 0),
            }

    def commit_chunk(
        self,
        transfer_id: str,
        claim: str,
        chunk_path: Path,
        start: int,
        end_exclusive: int,
        chunk_sha256: str,
    ) -> tuple[dict[str, Any], bool]:
        """Append one verified chunk or accept one exact durable replay."""
        with private_file_lock(self.lock_path):
            data = self._load(transfer_id)
            current_claim = data.get("claim")
            if (
                not isinstance(current_claim, dict)
                or current_claim.get("id") != claim
            ):
                raise TransferGatewayError("transfer claim changed")
            offset = int(data.get("offset") or 0)
            last = data.get("last_chunk")
            replay = start < offset
            if replay:
                if not (
                    isinstance(last, dict)
                    and int(last.get("start", -1)) == start
                    and int(last.get("end", -1)) == end_exclusive
                    and hmac.compare_digest(
                        str(last.get("sha256") or ""), chunk_sha256
                    )
                ):
                    raise TransferGatewayError(
                        "completed chunk cannot be replayed"
                    )
            elif start != offset:
                raise TransferGatewayError(
                    f"transfer offset conflict: expected {offset}, got {start}"
                )
            if not replay:
                try:
                    destination = self._open_spool(data, update=True)
                    try:
                        source = _open_transfer_source(chunk_path)
                    except Exception:
                        destination.close()
                        raise
                except TransferGatewayError:
                    raise
                except (FileNotFoundError, IsADirectoryError, OSError) as exc:
                    raise TransferGatewayError(
                        "transfer chunk or spool is missing or unsafe"
                    ) from exc
                with destination, source:
                    destination.seek(0, os.SEEK_END)
                    if destination.tell() != offset:
                        raise TransferGatewayError(
                            "transfer spool size changed"
                        )
                    try:
                        while chunk := source.read(1024 * 1024):
                            destination.write(chunk)
                        destination.flush()
                        os.fsync(destination.fileno())
                    except Exception as exc:
                        try:
                            destination.seek(offset)
                            destination.truncate(offset)
                            destination.flush()
                            os.fsync(destination.fileno())
                            rollback_identity = _spool_handle_identity(
                                destination
                            )
                            data["spool_identity_a"] = rollback_identity[0]
                            data["spool_identity_b"] = rollback_identity[1]
                            data["spool_identity_c"] = rollback_identity[2]
                            self._save(data)
                        except Exception as rollback_exc:
                            raise TransferGatewayError(
                                "transfer spool rollback failed"
                            ) from rollback_exc
                        if isinstance(exc, TransferGatewayError):
                            raise
                        raise TransferGatewayError(
                            "transfer spool write failed"
                        ) from exc
                    committed_identity = _spool_handle_identity(destination)
                    data["spool_identity_a"] = committed_identity[0]
                    data["spool_identity_b"] = committed_identity[1]
                    data["spool_identity_c"] = committed_identity[2]
                    data["offset"] = end_exclusive
                    data["last_chunk"] = {
                        "start": start,
                        "end": end_exclusive,
                        "sha256": chunk_sha256,
                    }
                    if end_exclusive == int(data["expected_bytes"]):
                        digest = hashlib.sha256()
                        destination.seek(0)
                        while chunk := destination.read(1024 * 1024):
                            digest.update(chunk)
                        if digest.hexdigest() != str(data["expected_sha256"]):
                            data["state"] = "failed"
                            data["claim"] = None
                            self._save(data)
                            raise TransferGatewayError(
                                "transfer digest mismatch"
                            )
                        data["state"] = "ready"
            data["claim"] = None
            self._save(data)
            return data, replay

    def object(
        self, transfer_id: str, *, require_ready: bool = True
    ) -> TransferObject:
        """Return a validated identity-bound view of one private spool."""
        with private_file_lock(self.lock_path):
            data = self._load(transfer_id)
            state = str(data.get("state") or "")
            if require_ready and state != "ready":
                raise TransferGatewayError("transfer object is not ready")
            path = self._spool_path(transfer_id)
            expected = int(data.get("expected_bytes") or 0)
            offset = int(data.get("offset") or 0)
            with self._open_spool(data) as handle:
                if os.fstat(handle.fileno()).st_size != offset:
                    raise TransferGatewayError("transfer spool size changed")
            identity = self._spool_identity(data)
            return TransferObject(
                transfer_id=transfer_id,
                path=path,
                expected_bytes=expected,
                expected_sha256=str(data.get("expected_sha256") or ""),
                offset=offset,
                state=state,
                identity_a=identity[0],
                identity_b=identity[1],
                identity_c=identity[2],
            )

    def consume(self, transfer_id: str) -> None:
        """Mark a published object consumed and revoke both capabilities."""
        with private_file_lock(self.lock_path):
            data = self._load(transfer_id)
            data["state"] = "consumed"
            data["upload_token_hash"] = None
            data["download_token_hash"] = None
            data["claim"] = None
            self._save(data)

    def suspend(self, transfer_id: str) -> None:
        """Revoke active grants while retaining validated progress for job retry."""
        with (
            private_file_lock(self.lock_path),
            contextlib.suppress(TransferGatewayError),
        ):
            data = self._load(transfer_id)
            data["upload_token_hash"] = None
            data["download_token_hash"] = None
            data["claim"] = None
            data["expires_at"] = time.time() + _RESUME_RETENTION_S
            self._save(data)

    def abort(self, transfer_id: str) -> None:
        """Mark a transfer aborted and revoke active capabilities."""
        with (
            private_file_lock(self.lock_path),
            contextlib.suppress(TransferGatewayError),
        ):
            data = self._load(transfer_id)
            data["state"] = "aborted"
            data["upload_token_hash"] = None
            data["download_token_hash"] = None
            data["claim"] = None
            self._save(data)

    def delete(self, transfer_id: str) -> None:
        """Delete one transfer's private metadata, spool, and scratch chunks."""
        with private_file_lock(self.lock_path):
            self._delete_locked(transfer_id)


def _http_error(exc: TransferGatewayError) -> JSONResponse:
    """Return one redacted stable private-gateway error response."""
    message = str(exc)
    status_code = 422
    if "not found" in message:
        status_code = 404
    elif "expired" in message:
        status_code = 410
    elif "authorization" in message:
        status_code = 401
    elif (
        "active claim" in message or "offset" in message or "replay" in message
    ):
        status_code = 409
    return JSONResponse(
        {"detail": message},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _direction_for_request(request: Request) -> Literal["upload", "download"]:
    if request.method == "PUT":
        return "upload"
    if request.method == "GET":
        return "download"
    requested = (request.headers.get(_DIRECTION_HEADER) or "").lower()
    if requested not in {"upload", "download"}:
        raise TransferGatewayError("transfer direction header is invalid")
    return requested  # type: ignore[return-value]


def _authorization(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("authorization"), request.headers.get(
        _WORKER_HEADER
    )


async def _read_chunk_to_private_file(
    request: Request, path: Path, expected_bytes: int
) -> tuple[int, str]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_BINARY", 0)),
        0o600,
    )
    received = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                received += len(chunk)
                if received > expected_bytes:
                    raise TransferGatewayError(
                        "upload body exceeds Content-Range"
                    )
                handle.write(chunk)
                digest.update(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if received != expected_bytes:
        path.unlink(missing_ok=True)
        raise TransferGatewayError("upload body does not match Content-Range")
    return received, digest.hexdigest()


def _open_transfer_object(obj: TransferObject) -> BinaryIO:
    """Open one spool without following replacement links and verify identity."""
    try:
        handle = _open_transfer_source(obj.path)
    except (FileNotFoundError, IsADirectoryError, OSError, ValueError) as exc:
        raise TransferGatewayError(
            "transfer spool is missing or unsafe"
        ) from exc
    if _spool_handle_identity(handle) != (
        obj.identity_a,
        obj.identity_b,
        obj.identity_c,
    ):
        handle.close()
        raise TransferGatewayError("transfer spool identity changed")
    return handle


def _download_iterator(
    store: TransferGatewayStore,
    transfer_id: str,
    claim: str,
    obj: TransferObject,
    start: int,
    length: int,
) -> Iterator[bytes]:
    try:
        with _open_transfer_object(obj) as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise TransferGatewayError(
                        "transfer spool ended unexpectedly"
                    )
                remaining -= len(chunk)
                yield chunk
    finally:
        store.release_claim(transfer_id, claim)


def build_transfer_gateway_router() -> tuple[BaseRoute, ...]:
    """Build Starlette-native private routes without adding an MCP tool."""

    async def transfer_route(request: Request):
        transfer_id = str(request.path_params["transfer_id"])
        store = TransferGatewayStore()
        authorization, worker = _authorization(request)
        try:
            if not authorization or not worker:
                raise TransferGatewayError("transfer authorization required")
            direction = _direction_for_request(request)
            store.authenticate(transfer_id, authorization, worker, direction)
            if request.method == "HEAD":
                status = store.status(transfer_id)
                return JSONResponse(
                    status,
                    status_code=200,
                    headers={
                        "Cache-Control": "no-store",
                        "X-Transfer-Offset": str(status["offset"]),
                        "X-Transfer-State": str(status["state"]),
                        "X-Transfer-Expected-Bytes": str(
                            status["expected_bytes"]
                        ),
                        "X-Transfer-Expected-SHA256": str(
                            status["expected_sha256"]
                        ),
                    },
                )
            if request.method == "PUT":
                content_range = request.headers.get("content-range") or ""
                match = _CONTENT_RANGE_RE.fullmatch(content_range)
                if match is None:
                    raise TransferGatewayError("malformed Content-Range")
                start, end_inclusive, total = (
                    int(value) for value in match.groups()
                )
                if (
                    end_inclusive < start
                    or total <= 0
                    or end_inclusive >= total
                ):
                    raise TransferGatewayError("malformed Content-Range")
                size = end_inclusive - start + 1
                if size > store.settings.remote_http_transfer_chunk_bytes:
                    raise TransferGatewayError(
                        "upload chunk exceeds configured limit"
                    )
                status = store.status(transfer_id)
                if total != int(status["expected_bytes"]):
                    raise TransferGatewayError("Content-Range total mismatch")
                header_length = request.headers.get("content-length")
                try:
                    parsed_length = int(header_length or "")
                except ValueError:
                    raise TransferGatewayError(
                        "Content-Length mismatch"
                    ) from None
                if parsed_length != size:
                    raise TransferGatewayError("Content-Length mismatch")
                expected_chunk_digest = (
                    request.headers.get(_CHUNK_DIGEST_HEADER) or ""
                ).lower()
                if not re.fullmatch(r"[0-9a-f]{64}", expected_chunk_digest):
                    raise TransferGatewayError("chunk digest header is invalid")
                _, claim = store.begin_claim(transfer_id, "upload")
                chunk_path = store._chunk_path(transfer_id, claim)
                try:
                    _, digest = await _read_chunk_to_private_file(
                        request, chunk_path, size
                    )
                    if digest != expected_chunk_digest:
                        raise TransferGatewayError(
                            "upload chunk digest mismatch"
                        )
                    data, replay = await asyncio.to_thread(
                        store.commit_chunk,
                        transfer_id,
                        claim,
                        chunk_path,
                        start,
                        end_inclusive + 1,
                        digest,
                    )
                except BaseException:
                    store.release_claim(transfer_id, claim)
                    raise
                finally:
                    chunk_path.unlink(missing_ok=True)
                return JSONResponse(
                    {
                        "offset": int(data["offset"]),
                        "state": str(data["state"]),
                        "replayed": replay,
                    },
                    status_code=200,
                    headers={"Cache-Control": "no-store"},
                )

            obj = store.object(transfer_id)
            range_header = request.headers.get("range") or ""
            match = _RANGE_RE.fullmatch(range_header)
            if match is None:
                raise TransferGatewayError("validated Range header is required")
            start = int(match.group(1))
            requested_end = int(match.group(2)) if match.group(2) else None
            if start < 0 or start >= obj.expected_bytes:
                raise TransferGatewayError("download range is unsatisfiable")
            maximum_end = min(
                obj.expected_bytes - 1,
                start + store.settings.remote_http_transfer_chunk_bytes - 1,
            )
            end = (
                maximum_end
                if requested_end is None
                else min(requested_end, maximum_end)
            )
            if end < start:
                raise TransferGatewayError("download range is unsatisfiable")
            _, claim = store.begin_claim(transfer_id, "download")
            length = end - start + 1
            return StreamingResponse(
                _download_iterator(
                    store, transfer_id, claim, obj, start, length
                ),
                status_code=206,
                media_type="application/octet-stream",
                headers={
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-store",
                    "Content-Length": str(length),
                    "Content-Range": (
                        f"bytes {start}-{end}/{obj.expected_bytes}"
                    ),
                    "X-Content-SHA256": obj.expected_sha256,
                },
            )
        except TransferGatewayError as exc:
            return _http_error(exc)

    return (
        Route(
            "/remote/transfer/{transfer_id}",
            transfer_route,
            methods=["HEAD", "GET", "PUT"],
        ),
    )


async def copy_spool_to_local_transaction(
    obj: TransferObject,
    *,
    destination_path: str,
    destination_session_id: str | None,
    destination_workdir: str | None = None,
    overwrite: bool,
    chunk_size: int,
    preserve_partial: bool = False,
) -> dict[str, Any]:
    """Publish a ready spool through the existing transactional writer."""
    from ..ops.transfer import (
        transfer_abort_write,
        transfer_begin_write,
        transfer_finish_write,
        transfer_write_bytes,
    )

    destination_scope = (
        {"workdir": destination_workdir}
        if destination_workdir is not None
        else {"session_id": destination_session_id}
    )
    begin = await asyncio.to_thread(
        transfer_begin_write,
        destination_path,
        overwrite,
        obj.expected_bytes,
        obj.transfer_id,
        **destination_scope,
    )
    transfer_id = begin.transfer_id
    chunks = 0
    offset = int(begin.offset)
    try:
        with _open_transfer_object(obj) as handle:
            handle.seek(offset)
            while chunk := handle.read(chunk_size):
                await asyncio.to_thread(
                    transfer_write_bytes,
                    destination_path,
                    transfer_id,
                    offset,
                    chunk,
                    hashlib.sha256(chunk).hexdigest(),
                    **destination_scope,
                )
                offset += len(chunk)
                chunks += 1
        finish = await asyncio.to_thread(
            transfer_finish_write,
            destination_path,
            transfer_id,
            obj.expected_bytes,
            obj.expected_sha256,
            **destination_scope,
        )
    except BaseException:
        if not preserve_partial:
            await asyncio.to_thread(
                transfer_abort_write,
                destination_path,
                transfer_id,
                **destination_scope,
            )
        raise
    return {
        "path": finish.path,
        "bytes": obj.expected_bytes,
        "sha256": obj.expected_sha256,
        "chunks": chunks,
        "chunk_size": chunk_size,
        "resumed_bytes": int(begin.offset),
    }
