"""Session-to-session copy helpers."""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Literal, cast

from ...remote.service import call_remote_worker_tool
from ...schemas.result_models.session import (
    SessionCopyEndpoint,
    SessionCopyOutput,
    SessionCopyRelation,
)
from ...tool_session.store import AgentSession, get_tool_session_store
from ...utils.serialization import to_jsonable
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


async def _cleanup_temp(endpoint: _Endpoint, path: str | None) -> None:
    if not path:
        return
    try:
        await _endpoint_transfer_data(
            endpoint,
            "transfer_delete_temp_path",
            {"path": path},
            session_bound=False,
        )
    except Exception:
        # Temp cleanup should not hide the primary copy failure/result.
        return


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
    src_session_bound: bool = True,
    dst_session_bound: bool = True,
) -> dict[str, Any]:
    chunk_bytes = normalize_chunk_size(chunk_size)
    stat = await _endpoint_transfer_data(
        src,
        "transfer_stat",
        {"path": src_path, "sha256": True},
        session_bound=src_session_bound,
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
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
        while offset < int(stat["size"]):
            chunk = await _endpoint_transfer_data(
                src,
                "transfer_read_chunk",
                {"path": src_path, "offset": offset, "chunk_size": chunk_bytes},
                session_bound=src_session_bound,
            )
            if int(chunk["bytes"]) == 0:
                break
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
            offset += int(chunk["bytes"])
            chunks += 1
        finish = await _endpoint_transfer_data(
            dst,
            "transfer_finish_write",
            {
                "path": dst_path,
                "transfer_id": transfer_id,
                "expected_bytes": stat["size"],
                "expected_sha256": stat.get("sha256"),
            },
            session_bound=dst_session_bound,
        )
    except Exception:
        with contextlib.suppress(Exception):
            await _endpoint_transfer_data(
                dst,
                "transfer_abort_write",
                {"path": dst_path, "transfer_id": transfer_id},
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
) -> dict[str, Any]:
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
    try:
        copy_result = await _copy_file(
            src,
            pack["archive_path"],
            dst,
            dst_archive["path"],
            overwrite=True,
            chunk_size=chunk_size,
            src_session_bound=False,
            dst_session_bound=False,
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
    except Exception:
        await _cleanup_temp(dst, dst_archive.get("path"))
        raise
    finally:
        await _cleanup_temp(src, pack.get("archive_path"))
    return {
        "source_path": pack["path"],
        "destination_path": unpack["path"],
        "archive_bytes": pack["bytes"],
        "archive_sha256": pack["sha256"],
        "chunks": copy_result["chunks"],
        "entries": unpack["entries"],
    }


async def session_copy_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: SessionCopyKind = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> SessionCopyOutput:
    """Copy a file or directory between two explicit sessions."""
    store = get_tool_session_store()
    src_session = store.touch_session(src_session_id)
    dst_session = store.touch_session(dst_session_id)
    src = _Endpoint(src_session)
    dst = _Endpoint(dst_session)

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
        )
    else:
        metrics = await _copy_dir(
            src,
            src_path,
            dst,
            dst_path,
            overwrite=overwrite,
            chunk_size=chunk_size,
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
    )
