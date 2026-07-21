"""Session-to-session copy helpers."""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal, cast

from ...remote.service import call_remote_worker_tool
from ...schemas.result_models.jobs import JobStartOutput
from ...schemas.result_models.session import (
    SessionCopyEndpoint,
    SessionCopyOutput,
    SessionCopyRelation,
)
from ...tool_session.store import AgentSession, get_tool_session_store
from ...utils.serialization import to_jsonable
from ..jobs import (
    ManagedJobContext,
    register_managed_job_handler,
    start_managed_job,
)
from ..transfer import (
    normalize_chunk_size,
    transfer_abort_write,
    transfer_alloc_temp_path,
    transfer_begin_write,
    transfer_delete_temp_path,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_chunk,
)
from .remote_session import call_remote_session_tool

SessionCopyKind = Literal["auto", "file", "dir"]
SessionCopyRoute = Literal[
    "local_to_local",
    "local_to_remote",
    "remote_to_local",
    "remote_to_remote_same_machine",
    "remote_to_remote_different_machines",
]
SessionCopyProgress = Callable[[dict[str, Any]], Awaitable[None]]


async def _report_progress(
    progress: SessionCopyProgress | None, **fields: Any
) -> None:
    """Publish one structured progress snapshot when a callback is configured."""
    if progress is not None:
        await progress(fields)


@dataclass(frozen=True)
class _Endpoint:
    """One side of a session-to-session copy."""

    session: AgentSession

    @property
    def label(self) -> str:
        if self.session.target == "local":
            return "local"
        if self.session.machine:
            return self.session.machine
        return "remote"


def _json_dict(value: Any) -> dict[str, Any]:
    jsonable = to_jsonable(value)
    if isinstance(jsonable, dict):
        return cast(dict[str, Any], jsonable)
    return {"result": jsonable}


async def _remote_raw_transfer_data(
    endpoint: _Endpoint, tool: str, args: dict[str, Any]
) -> dict[str, Any]:
    if endpoint.session.target != "remote" or not endpoint.session.machine:
        raise ValueError("raw remote transfer calls require a remote session")
    result = await call_remote_worker_tool(endpoint.session.machine, tool, args)
    if not result.get("ok", False):
        raise RuntimeError(
            str(result.get("message") or f"remote {tool} failed")
        )
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        message = data.get("message") or f"remote {tool} failed"
        error_type = data.get("error_type") or "remote_error"
        raise RuntimeError(f"{error_type}: {message}")
    return _json_dict(data)


async def _endpoint_transfer_data(
    endpoint: _Endpoint,
    tool: str,
    args: dict[str, Any],
    *,
    session_bound: bool = True,
) -> dict[str, Any]:
    """Run a transfer primitive on one copy endpoint."""
    if endpoint.session.target == "remote":
        if session_bound:
            return await call_remote_session_tool(endpoint.session, tool, args)
        return await _remote_raw_transfer_data(endpoint, tool, args)

    session_id = endpoint.session.session_id if session_bound else None
    if tool == "transfer_stat":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_stat(
                    args["path"],
                    args.get("sha256", True),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_read_chunk":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_read_chunk(
                    args["path"],
                    args.get("offset", 0),
                    args.get("chunk_size"),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_begin_write":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_begin_write(
                    args["path"],
                    args.get("overwrite", True),
                    args.get("expected_bytes"),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_write_chunk":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_write_chunk(
                    args["path"],
                    args["transfer_id"],
                    args["offset"],
                    args["data_b64"],
                    args.get("expected_sha256"),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_finish_write":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_finish_write(
                    args["path"],
                    args["transfer_id"],
                    args.get("expected_bytes"),
                    args.get("expected_sha256"),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_abort_write":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_abort_write(
                    args["path"],
                    args["transfer_id"],
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_alloc_temp_path":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_alloc_temp_path(
                    args.get("suffix", ".bin"), session_id=session_id
                )
            )
        )
    if tool == "transfer_pack_dir":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_pack_dir(
                    args["path"],
                    args.get("compression", "gz"),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_unpack_archive":
        return await asyncio.to_thread(
            lambda: _json_dict(
                transfer_unpack_archive(
                    args["archive_path"],
                    args["dst_path"],
                    args.get("overwrite", True),
                    args.get("cleanup_archive", True),
                    session_id=session_id,
                )
            )
        )
    if tool == "transfer_delete_temp_path":
        return await asyncio.to_thread(
            lambda: _json_dict(transfer_delete_temp_path(args["path"]))
        )
    raise ValueError(f"unsupported transfer tool: {tool}")


async def _run_cleanup(operation: Any) -> None:
    """Finish one best-effort cleanup even when the caller is cancelled."""
    task = asyncio.create_task(operation)
    try:
        await asyncio.shield(task)
    except BaseException:
        with contextlib.suppress(BaseException):
            await task


async def _cleanup_temp(endpoint: _Endpoint, path: str | None) -> None:
    if not path:
        return
    await _run_cleanup(
        _endpoint_transfer_data(
            endpoint,
            "transfer_delete_temp_path",
            {"path": path},
            session_bound=False,
        )
    )


async def _abort_transfer(
    endpoint: _Endpoint,
    path: str,
    transfer_id: str,
    *,
    session_bound: bool,
) -> None:
    """Best-effort abort one destination write without hiding its primary failure."""
    await _run_cleanup(
        _endpoint_transfer_data(
            endpoint,
            "transfer_abort_write",
            {"path": path, "transfer_id": transfer_id},
            session_bound=session_bound,
        )
    )


def _copy_route(src: AgentSession, dst: AgentSession) -> SessionCopyRoute:
    if src.target == "local" and dst.target == "local":
        return "local_to_local"
    if src.target == "local" and dst.target == "remote":
        return "local_to_remote"
    if src.target == "remote" and dst.target == "local":
        return "remote_to_local"
    if src.machine == dst.machine:
        return "remote_to_remote_same_machine"
    return "remote_to_remote_different_machines"


def _relation(src: AgentSession, dst: AgentSession) -> SessionCopyRelation:
    return SessionCopyRelation(
        route=_copy_route(src, dst),
        same_session=src.session_id == dst.session_id,
        same_target=src.target == dst.target,
        same_machine=(
            src.target == "remote"
            and dst.target == "remote"
            and src.machine == dst.machine
        ),
    )


def _endpoint_model(session: AgentSession, path: str) -> SessionCopyEndpoint:
    return SessionCopyEndpoint(
        session_id=session.session_id,
        target=session.target,
        machine=session.machine,
        workdir=session.workdir,
        path=path,
    )


async def _copy_file(
    src: _Endpoint,
    src_path: str,
    dst: _Endpoint,
    dst_path: str,
    *,
    overwrite: bool,
    chunk_size: int | None,
    progress: SessionCopyProgress | None = None,
    src_session_bound: bool = True,
    dst_session_bound: bool = True,
) -> dict[str, Any]:
    chunk_bytes = normalize_chunk_size(chunk_size)
    same_remote_worker = (
        src.session.target == "remote"
        and dst.session.target == "remote"
        and src.session.machine == dst.session.machine
    )
    if same_remote_worker:
        source_session_id = (
            src.session.worker_session_id if src_session_bound else None
        )
        destination_session_id = (
            dst.session.worker_session_id if dst_session_bound else None
        )
        if src_session_bound and not source_session_id:
            raise RuntimeError(
                "remote source session is missing worker_session_id"
            )
        if dst_session_bound and not destination_session_id:
            raise RuntimeError(
                "remote destination session is missing worker_session_id"
            )
        copied = await _remote_raw_transfer_data(
            src,
            "transfer_copy_file",
            {
                "source_path": src_path,
                "destination_path": dst_path,
                "overwrite": overwrite,
                "chunk_size": chunk_bytes,
                "source_session_id": source_session_id,
                "destination_session_id": destination_session_id,
            },
        )
        await _report_progress(
            progress,
            phase="transferring",
            bytes_transferred=int(copied["bytes"]),
            total_bytes=int(copied["bytes"]),
            chunks=int(copied["chunks"]),
            chunk_size=int(copied["chunk_size"]),
        )
        return {
            "source_path": copied["source_path"],
            "destination_path": copied["path"],
            "bytes": copied["bytes"],
            "sha256": copied["sha256"],
            "chunks": copied["chunks"],
            "chunk_size": copied["chunk_size"],
        }

    stat = await _endpoint_transfer_data(
        src,
        "transfer_stat",
        {"path": src_path, "sha256": True},
        session_bound=src_session_bound,
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    source_size = int(stat["size"])
    await _report_progress(
        progress,
        phase="transferring",
        bytes_transferred=0,
        total_bytes=source_size,
        chunks=0,
        chunk_size=chunk_bytes,
    )
    begin = await _endpoint_transfer_data(
        dst,
        "transfer_begin_write",
        {
            "path": dst_path,
            "overwrite": overwrite,
            "expected_bytes": stat["size"],
        },
        session_bound=dst_session_bound,
    )
    transfer_id = str(begin["transfer_id"])
    chunks = 0
    offset = 0
    try:
        while offset < source_size:
            chunk = await _endpoint_transfer_data(
                src,
                "transfer_read_chunk",
                {"path": src_path, "offset": offset, "chunk_size": chunk_bytes},
                session_bound=src_session_bound,
            )
            chunk_offset = int(chunk["offset"])
            chunk_size_received = int(chunk["bytes"])
            chunk_source_size = int(chunk["size"])
            if chunk_offset != offset:
                raise RuntimeError(
                    f"source chunk offset mismatch: expected {offset}, got {chunk_offset}"
                )
            if chunk_source_size != source_size:
                raise RuntimeError(
                    "source size changed during transfer: "
                    f"expected {source_size}, got {chunk_source_size}"
                )
            if chunk_size_received <= 0:
                raise RuntimeError("source transfer ended before completion")
            next_offset = offset + chunk_size_received
            eof = bool(chunk.get("eof", False))
            if eof != (next_offset >= source_size):
                raise RuntimeError("source transfer EOF marker is inconsistent")
            await _endpoint_transfer_data(
                dst,
                "transfer_write_chunk",
                {
                    "path": dst_path,
                    "transfer_id": transfer_id,
                    "offset": offset,
                    "data_b64": chunk["data_b64"],
                    "expected_sha256": chunk["sha256"],
                },
                session_bound=dst_session_bound,
            )
            offset = next_offset
            chunks += 1
            await _report_progress(
                progress,
                phase="transferring",
                bytes_transferred=offset,
                total_bytes=source_size,
                chunks=chunks,
                chunk_size=chunk_bytes,
            )
        finish = await _endpoint_transfer_data(
            dst,
            "transfer_finish_write",
            {
                "path": dst_path,
                "transfer_id": transfer_id,
                "expected_bytes": source_size,
                "expected_sha256": stat.get("sha256"),
            },
            session_bound=dst_session_bound,
        )
    except BaseException:
        await _abort_transfer(
            dst,
            dst_path,
            transfer_id,
            session_bound=dst_session_bound,
        )
        raise
    return {
        "source_path": stat["path"],
        "destination_path": finish["path"],
        "bytes": stat["size"],
        "sha256": stat.get("sha256"),
        "chunks": chunks,
        "chunk_size": chunk_bytes,
    }


async def _copy_dir(
    src: _Endpoint,
    src_path: str,
    dst: _Endpoint,
    dst_path: str,
    *,
    overwrite: bool,
    chunk_size: int | None,
    progress: SessionCopyProgress | None = None,
) -> dict[str, Any]:
    await _report_progress(progress, phase="packing", bytes_transferred=0)
    pack: dict[str, Any] = {}
    dst_archive: dict[str, Any] = {}
    try:
        pack = await _endpoint_transfer_data(
            src,
            "transfer_pack_dir",
            {"path": src_path, "compression": "gz"},
        )
        dst_archive = await _endpoint_transfer_data(
            dst,
            "transfer_alloc_temp_path",
            {"suffix": ".tar.gz"},
            session_bound=False,
        )
        copy_result = await _copy_file(
            src,
            pack["archive_path"],
            dst,
            dst_archive["path"],
            overwrite=True,
            chunk_size=chunk_size,
            progress=progress,
            src_session_bound=False,
            dst_session_bound=False,
        )
        await _report_progress(
            progress,
            phase="unpacking",
            bytes_transferred=int(pack["bytes"]),
            total_bytes=int(pack["bytes"]),
            chunks=int(copy_result["chunks"]),
            chunk_size=normalize_chunk_size(chunk_size),
        )
        unpack = await _endpoint_transfer_data(
            dst,
            "transfer_unpack_archive",
            {
                "archive_path": dst_archive["path"],
                "dst_path": dst_path,
                "overwrite": overwrite,
                "cleanup_archive": True,
            },
        )
    finally:
        await _cleanup_temp(dst, dst_archive.get("path"))
        await _cleanup_temp(src, pack.get("archive_path"))
    return {
        "source_path": pack["path"],
        "destination_path": unpack["path"],
        "archive_bytes": pack["bytes"],
        "archive_sha256": pack["sha256"],
        "chunks": copy_result["chunks"],
        "entries": unpack["entries"],
        "cleanup_errors": list(unpack.get("cleanup_errors") or []),
    }


async def session_copy_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: SessionCopyKind = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
    *,
    progress: SessionCopyProgress | None = None,
) -> SessionCopyOutput:
    """Copy a file or directory between two explicit sessions."""
    store = get_tool_session_store()
    src_session = store.touch_session(src_session_id)
    dst_session = store.touch_session(dst_session_id)
    src = _Endpoint(src_session)
    dst = _Endpoint(dst_session)
    await _report_progress(progress, phase="preparing", bytes_transferred=0)

    stat = await _endpoint_transfer_data(
        src, "transfer_stat", {"path": src_path, "sha256": kind != "dir"}
    )
    source_type = stat.get("type")
    resolved_kind: Literal["file", "dir"]
    if kind == "auto":
        if source_type not in {"file", "dir"}:
            raise ValueError(f"unsupported source type for copy: {source_type}")
        resolved_kind = cast(Literal["file", "dir"], source_type)
    elif kind != source_type:
        raise ValueError(f"source is {source_type}, not requested kind {kind}")
    else:
        resolved_kind = kind

    if resolved_kind == "file":
        metrics = await _copy_file(
            src,
            src_path,
            dst,
            dst_path,
            overwrite=overwrite,
            chunk_size=chunk_size,
            progress=progress,
        )
    else:
        metrics = await _copy_dir(
            src,
            src_path,
            dst,
            dst_path,
            overwrite=overwrite,
            chunk_size=chunk_size,
            progress=progress,
        )

    source_model = _endpoint_model(src_session, src_path)
    destination_model = _endpoint_model(dst_session, dst_path)
    source_model.resolved_path = metrics.get("source_path")
    destination_model.resolved_path = metrics.get("destination_path")

    return SessionCopyOutput(
        kind=resolved_kind,
        source=source_model,
        destination=destination_model,
        relation=_relation(src_session, dst_session),
        bytes=metrics.get("bytes"),
        sha256=metrics.get("sha256"),
        archive_bytes=metrics.get("archive_bytes"),
        archive_sha256=metrics.get("archive_sha256"),
        chunks=int(metrics.get("chunks", 0)),
        chunk_size=normalize_chunk_size(chunk_size),
        entries=metrics.get("entries"),
        cleanup_errors=list(metrics.get("cleanup_errors") or []),
    )


SESSION_COPY_MANAGED_KIND = "session-copy"


async def _run_session_copy_job(
    context: ManagedJobContext, payload: dict[str, Any]
) -> dict[str, Any]:
    """Run one durable session-copy managed job from its stored payload."""
    last_report_at = 0.0
    last_phase = ""

    async def report(progress: dict[str, Any]) -> None:
        nonlocal last_phase, last_report_at
        now = time.monotonic()
        phase = str(progress.get("phase") or "")
        transferred = int(progress.get("bytes_transferred") or 0)
        total = int(progress.get("total_bytes") or 0)
        if (
            phase != last_phase
            or transferred == 0
            or (total > 0 and transferred >= total)
            or now - last_report_at >= 0.5
        ):
            await context.update_progress(**progress)
            last_phase = phase
            last_report_at = now

    src_session_id = str(payload["src_session_id"])
    src_path = str(payload["src_path"])
    dst_session_id = str(payload["dst_session_id"])
    dst_path = str(payload["dst_path"])
    kind = cast(SessionCopyKind, str(payload.get("kind") or "auto"))
    overwrite = bool(payload.get("overwrite", True))
    raw_chunk_size = payload.get("chunk_size")
    chunk_size = int(raw_chunk_size) if raw_chunk_size is not None else None

    await context.log(
        f"copying {src_session_id}:{src_path} -> {dst_session_id}:{dst_path}"
    )
    result = await session_copy_execute(
        src_session_id,
        src_path,
        dst_session_id,
        dst_path,
        kind,
        overwrite,
        chunk_size,
        progress=report,
    )
    total_bytes = int(result.bytes or result.archive_bytes or 0)
    await context.update_progress(
        phase="completed",
        bytes_transferred=total_bytes,
        total_bytes=total_bytes,
        chunks=result.chunks,
        chunk_size=result.chunk_size,
        kind=result.kind,
        route=result.relation.route,
    )
    await context.log(
        f"copy completed: {result.kind}, {total_bytes} bytes, {result.chunks} chunks"
    )
    return result.model_dump(mode="json")


async def session_copy_job_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: SessionCopyKind = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> JobStartOutput:
    """Start a controller-managed session copy and return its tracked job."""
    store = get_tool_session_store()
    store.touch_session(src_session_id)
    store.touch_session(dst_session_id)
    normalized_chunk_size = normalize_chunk_size(chunk_size)
    payload = {
        "src_session_id": src_session_id,
        "src_path": src_path,
        "dst_session_id": dst_session_id,
        "dst_path": dst_path,
        "kind": kind,
        "overwrite": overwrite,
        "chunk_size": normalized_chunk_size,
    }
    destination_name = PurePath(dst_path).name or "artifact"
    return await start_managed_job(
        src_session_id,
        SESSION_COPY_MANAGED_KIND,
        payload,
        name=f"copy-{destination_name}"[:80],
        command=(
            f"session_copy {src_session_id}:{src_path} -> "
            f"{dst_session_id}:{dst_path}"
        ),
        cwd=".",
    )


register_managed_job_handler(SESSION_COPY_MANAGED_KIND, _run_session_copy_job)
