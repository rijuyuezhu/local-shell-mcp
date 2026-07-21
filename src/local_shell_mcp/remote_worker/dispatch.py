"""Remote-worker-only tool dispatch.

This module bypasses tools.local_handlers/discovery so the worker does not import
the full MCP/FastAPI control-plane registry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from local_shell_mcp.remote.tool_specs import REMOTE_WORKER_TOOL_NAMES

WorkerHandler = Callable[[dict[str, Any]], Awaitable[Any]]


async def _session_start(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.session import session_start_execute

    return await session_start_execute(
        str(args.get("workdir") or "."),
        str(args.get("target") or "local"),
        args.get("machine"),
        args.get("label"),
    )


async def _query_audit(args: dict[str, Any]) -> Any:
    from local_shell_mcp.audit import query_audit

    return await asyncio.to_thread(
        query_audit,
        limit=int(args.get("limit") or 300),
        event=args.get("event"),
        operation=args.get("operation"),
        session=args.get("session"),
        search=args.get("search"),
        start_ts=args.get("start_ts"),
        end_ts=args.get("end_ts"),
        sort=str(args.get("sort") or "desc"),
    )


async def _get_audit_entry(args: dict[str, Any]) -> Any:
    from local_shell_mcp.audit import get_audit_entry

    return await asyncio.to_thread(get_audit_entry, str(args.get("id") or ""))


async def _dashboard_snapshot(args: dict[str, Any]) -> Any:  # noqa: ARG001
    from local_shell_mcp.dashboard import dashboard_snapshot

    return await asyncio.to_thread(dashboard_snapshot)


async def _bash(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import bash_execute

    return await bash_execute(
        str(args["session_id"]),
        str(args["command"]),
        str(args.get("cwd") or "."),
        args.get("timeout_s"),
        args.get("max_output_bytes"),
        args.get("env"),
        bool(args.get("async_", False)),
        bool(args.get("pty", False)),
        args.get("name"),
    )


async def _run_python_code(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import run_python_code_execute

    return await run_python_code_execute(
        str(args["session_id"]),
        str(args["code"]),
        str(args.get("cwd") or "."),
        args.get("timeout_s"),
        args.get("max_output_bytes"),
        args.get("env"),
        bool(args.get("async_", False)),
        bool(args.get("pty", False)),
        args.get("name"),
    )


async def _open_terminal_bridge(args: dict[str, Any]) -> Any:
    from local_shell_mcp.terminal_bridge import open_terminal_bridge_execute

    return await open_terminal_bridge_execute(
        str(args["shell_id"]),
        int(args.get("cols") or 120),
        int(args.get("rows") or 36),
    )


async def _read_terminal_bridge(args: dict[str, Any]) -> Any:
    from local_shell_mcp.terminal_bridge import read_terminal_bridge_execute

    return await read_terminal_bridge_execute(
        str(args["bridge_id"]),
        int(args.get("max_bytes") or 65_536),
        int(args.get("wait_ms") or 0),
    )


async def _write_terminal_bridge(args: dict[str, Any]) -> Any:
    from local_shell_mcp.terminal_bridge import write_terminal_bridge_execute

    return await write_terminal_bridge_execute(
        str(args["bridge_id"]),
        str(args.get("data_b64") or ""),
    )


async def _resize_terminal_bridge(args: dict[str, Any]) -> Any:
    from local_shell_mcp.terminal_bridge import resize_terminal_bridge_execute

    return await resize_terminal_bridge_execute(
        str(args["bridge_id"]),
        int(args["cols"]),
        int(args["rows"]),
    )


async def _close_terminal_bridge(args: dict[str, Any]) -> Any:
    from local_shell_mcp.terminal_bridge import close_terminal_bridge_execute

    return await close_terminal_bridge_execute(str(args["bridge_id"]))


async def _start_persistent_shell(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import start_persistent_shell_execute

    return await start_persistent_shell_execute(
        str(args.get("cwd") or "."),
        str(args["name"]) if args.get("name") is not None else None,
        str(args["command"]) if args.get("command") is not None else None,
    )


async def _send_persistent_shell_input(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import send_persistent_shell_input_execute

    return await send_persistent_shell_input_execute(
        str(args["shell_id"]),
        str(args.get("input_text") or ""),
        bool(args.get("enter", True)),
    )


async def _resize_persistent_shell(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import resize_persistent_shell_execute

    return await resize_persistent_shell_execute(
        str(args["shell_id"]), int(args["cols"]), int(args["rows"])
    )


async def _read_persistent_shell_output(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import read_persistent_shell_output_execute

    preserve_ansi = args.get("preserve_ansi", False)
    if not isinstance(preserve_ansi, bool):
        raise ValueError("preserve_ansi must be a boolean")
    return await read_persistent_shell_output_execute(
        str(args["shell_id"]),
        int(args.get("lines") or 200),
        preserve_ansi=preserve_ansi,
    )


async def _kill_persistent_shell(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import kill_persistent_shell_execute

    return await kill_persistent_shell_execute(str(args["shell_id"]))


async def _list_persistent_shells(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.shell import list_persistent_shells_execute

    return await list_persistent_shells_execute()


async def _job(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.jobs import job_execute

    return await job_execute(
        str(args["session_id"]),
        bool(args.get("list_jobs", False)),
        args.get("poll"),
        args.get("cancel"),
        args.get("retry"),
        bool(args.get("include_finished", True)),
        int(args.get("lines") or 200),
    )


async def _read_todos(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.todo import read_todos_execute

    return await asyncio.to_thread(read_todos_execute, str(args["session_id"]))


async def _write_todos(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.todo import write_todos_execute

    return await asyncio.to_thread(
        write_todos_execute,
        list(args.get("todos") or []),
        str(args["session_id"]),
        args.get("expected_revision"),
    )


async def _list_files(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.files import list_files_dispatch_execute

    return await list_files_dispatch_execute(
        str(args.get("path") or "."),
        bool(args.get("recursive", False)),
        int(args.get("max_entries") or 500),
        str(args["session_id"]),
    )


async def _write_file(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.files import write_file_dispatch_execute

    return await write_file_dispatch_execute(
        str(args["path"]),
        str(args.get("content") or ""),
        bool(args.get("overwrite", True)),
        str(args["session_id"]),
    )


async def _edit_lines(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.files import edit_lines_dispatch_execute

    return await edit_lines_dispatch_execute(
        str(args["path"]),
        int(args["start_line"]),
        int(args["end_line"]),
        str(args.get("replacement") or ""),
        args.get("snapshot_id"),
        str(args["session_id"]),
    )


async def _hashline_edit(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.files import hashline_edit_dispatch_execute

    return await hashline_edit_dispatch_execute(
        str(args["input"]), str(args["session_id"])
    )


async def _apply_patch(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.patch import apply_patch_dispatch_execute

    return await apply_patch_dispatch_execute(
        str(args["patch"]),
        str(args.get("cwd") or "."),
        str(args["session_id"]),
    )


async def _delete_file_or_dir(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.files import delete_file_or_dir_dispatch_execute

    return await delete_file_or_dir_dispatch_execute(
        str(args["path"]),
        bool(args.get("recursive", False)),
        str(args["session_id"]),
    )


async def _read(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.read import read_execute

    return await read_execute(str(args["path"]), str(args["session_id"]))


async def _tree_view(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.search import tree_view_execute

    return await tree_view_execute(
        str(args["session_id"]),
        str(args.get("cwd") or "."),
        int(args.get("depth") or 3),
        int(args.get("max_entries") or 500),
    )


async def _glob_search(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.search import glob_search_execute

    return await glob_search_execute(
        str(args["session_id"]),
        str(args["pattern"]),
        str(args.get("cwd") or "."),
        int(args.get("max_results") or 500),
    )


async def _search(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.search import search_execute

    return await search_execute(
        str(args["pattern"]),
        args.get("paths"),
        ".",
        bool(args.get("regex", True)),
        bool(args.get("case_sensitive", True)),
        args.get("max_results"),
        str(args["session_id"]),
        int(args.get("skip") or 0),
        bool(args.get("gitignore", True)),
    )


async def _secret_scan(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.secret_scan import secret_scan_execute

    return await secret_scan_execute(
        str(args.get("cwd") or "."),
        args.get("glob"),
        int(args.get("max_results") or 200),
        str(args["session_id"]),
    )


async def _transfer_stat(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_stat

    return await asyncio.to_thread(
        transfer_stat,
        str(args["path"]),
        bool(args.get("sha256", True)),
        session_id=args.get("session_id"),
    )


async def _transfer_copy_file(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_copy_file

    return await asyncio.to_thread(
        transfer_copy_file,
        str(args["source_path"]),
        str(args["destination_path"]),
        bool(args.get("overwrite", True)),
        args.get("chunk_size"),
        source_session_id=args.get("source_session_id"),
        destination_session_id=args.get("destination_session_id"),
    )


async def _transfer_read_chunk(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_read_chunk

    return await asyncio.to_thread(
        transfer_read_chunk,
        str(args["path"]),
        int(args.get("offset") or 0),
        args.get("chunk_size"),
        session_id=args.get("session_id"),
    )


async def _transfer_begin_write(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_begin_write

    return await asyncio.to_thread(
        transfer_begin_write,
        str(args["path"]),
        bool(args.get("overwrite", True)),
        args.get("expected_bytes"),
        session_id=args.get("session_id"),
    )


async def _transfer_write_chunk(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_write_chunk

    return await asyncio.to_thread(
        transfer_write_chunk,
        str(args["path"]),
        str(args["transfer_id"]),
        int(args["offset"]),
        str(args["data_b64"]),
        args.get("expected_sha256"),
        session_id=args.get("session_id"),
    )


async def _transfer_finish_write(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_finish_write

    return await asyncio.to_thread(
        transfer_finish_write,
        str(args["path"]),
        str(args["transfer_id"]),
        args.get("expected_bytes"),
        args.get("expected_sha256"),
        session_id=args.get("session_id"),
    )


async def _transfer_abort_write(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_abort_write

    return await asyncio.to_thread(
        transfer_abort_write,
        str(args["path"]),
        str(args["transfer_id"]),
        session_id=args.get("session_id"),
    )


async def _transfer_alloc_temp_path(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_alloc_temp_path

    return await asyncio.to_thread(
        transfer_alloc_temp_path,
        str(args.get("suffix") or ".bin"),
        session_id=args.get("session_id"),
    )


async def _transfer_pack_dir(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_pack_dir

    return await asyncio.to_thread(
        transfer_pack_dir,
        str(args["path"]),
        str(args.get("compression") or "gz"),
        session_id=args.get("session_id"),
    )


async def _transfer_unpack_archive(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_unpack_archive

    return await asyncio.to_thread(
        transfer_unpack_archive,
        str(args["archive_path"]),
        str(args["dst_path"]),
        bool(args.get("overwrite", True)),
        bool(args.get("cleanup_archive", True)),
        session_id=args.get("session_id"),
    )


async def _transfer_delete_temp_path(args: dict[str, Any]) -> Any:
    from local_shell_mcp.ops.transfer import transfer_delete_temp_path

    return await asyncio.to_thread(transfer_delete_temp_path, str(args["path"]))


_HANDLERS: dict[str, WorkerHandler] = {
    "session_start": _session_start,
    "dashboard_snapshot": _dashboard_snapshot,
    "query_audit": _query_audit,
    "get_audit_entry": _get_audit_entry,
    "read_todos": _read_todos,
    "write_todos": _write_todos,
    "bash": _bash,
    "run_python_code": _run_python_code,
    "open_terminal_bridge": _open_terminal_bridge,
    "read_terminal_bridge": _read_terminal_bridge,
    "write_terminal_bridge": _write_terminal_bridge,
    "resize_terminal_bridge": _resize_terminal_bridge,
    "close_terminal_bridge": _close_terminal_bridge,
    "start_persistent_shell": _start_persistent_shell,
    "send_persistent_shell_input": _send_persistent_shell_input,
    "resize_persistent_shell": _resize_persistent_shell,
    "read_persistent_shell_output": _read_persistent_shell_output,
    "kill_persistent_shell": _kill_persistent_shell,
    "list_persistent_shells": _list_persistent_shells,
    "job": _job,
    "list_files": _list_files,
    "write_file": _write_file,
    "edit_lines": _edit_lines,
    "hashline_edit": _hashline_edit,
    "apply_patch": _apply_patch,
    "delete_file_or_dir": _delete_file_or_dir,
    "read": _read,
    "tree_view": _tree_view,
    "glob_search": _glob_search,
    "search": _search,
    "secret_scan": _secret_scan,
    "transfer_stat": _transfer_stat,
    "transfer_copy_file": _transfer_copy_file,
    "transfer_read_chunk": _transfer_read_chunk,
    "transfer_begin_write": _transfer_begin_write,
    "transfer_write_chunk": _transfer_write_chunk,
    "transfer_finish_write": _transfer_finish_write,
    "transfer_abort_write": _transfer_abort_write,
    "transfer_alloc_temp_path": _transfer_alloc_temp_path,
    "transfer_pack_dir": _transfer_pack_dir,
    "transfer_unpack_archive": _transfer_unpack_archive,
    "transfer_delete_temp_path": _transfer_delete_temp_path,
}


async def execute_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    """Execute one allowlisted remote-worker tool."""
    if tool not in REMOTE_WORKER_TOOL_NAMES:
        raise ValueError(f"unsupported remote worker tool: {tool}")
    try:
        handler = _HANDLERS[tool]
    except KeyError as exc:
        raise ValueError(f"unsupported remote worker tool: {tool}") from exc
    return await handler(args or {})
