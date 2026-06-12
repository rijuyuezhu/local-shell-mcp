"""Remote worker-side tool dispatch, process loop, and CLI helpers."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import socket
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..config.settings import safe_settings_dump
from ..ops.fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    multi_edit_text,
    prune_temp_dir,
    read_text,
    relative_display,
    temp_dir,
    write_text,
)
from ..ops.search_ops import grep, tree
from ..ops.shell_ops import (
    kill_shell,
    list_shells,
    public_run_shell,
    public_run_shell_timeout,
    read_shell,
    run_shell,
    send_shell,
    start_shell,
)
from .constants import REMOTE_API_PREFIX


async def _to_thread(func, *args, **kwargs):
    """Run blocking local helpers in a thread when executing worker tools asynchronously."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _handled_remote_exception(exc: Exception) -> dict[str, Any]:
    """Convert local helper failures into serializable worker-side error payloads."""
    return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _read_many_files_sync(
    paths: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = 256,
) -> dict[str, Any]:
    """Read multiple files on a worker while preserving per-file errors in the response list."""
    files = [
        read_text(
            path, start_line, end_line, binary_preview, binary_preview_bytes
        )
        for path in paths
    ]
    return {
        "files": files,
        "total_content_bytes": sum(
            len(str(item.get("content") or item.get("preview") or "").encode())
            for item in files
        ),
    }


async def _apply_patch_text(patch: str, cwd: str = ".") -> dict[str, Any]:
    """Apply a unified diff on a worker through stdin and return the git-apply result."""
    await _to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"remote-patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await _to_thread(patch_path.write_text, patch, encoding="utf-8")
    result = await run_shell(
        f"git apply --check {shlex.quote(str(patch_path))} && git apply {shlex.quote(str(patch_path))}",
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def _run_python(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> dict[str, Any]:
    """Execute Python code from a temporary file on a worker and clean up the file afterwards."""
    await _to_thread(prune_temp_dir)
    script = temp_dir() / f"remote-script-{uuid.uuid4().hex}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    await _to_thread(script.write_text, code, encoding="utf-8")
    result = await run_shell(
        f"python3 {shlex.quote(str(script))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(script)}


async def execute_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    """Dispatch a remote-worker tool call to the matching local helper."""
    match tool:
        case "environment_info":
            result = await run_shell(
                "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
                cwd=".",
                timeout_s=10,
            )
            return {
                "settings": safe_settings_dump(),
                "probe": result.model_dump(),
            }
        case "run_shell_tool":
            return (
                await public_run_shell(
                    args["command"],
                    args.get("cwd", "."),
                    args.get("timeout_s"),
                    args.get("max_output_bytes"),
                )
            ).model_dump()
        case "run_python_tool":
            return await _run_python(
                args["code"], args.get("cwd", "."), args.get("timeout_s", 60)
            )
        case "shell_start":
            return await start_shell(
                args.get("cwd", "."), args.get("name"), args.get("command")
            )
        case "shell_send":
            return await send_shell(
                args["session_id"], args["input_text"], args.get("enter", True)
            )
        case "shell_read":
            return await read_shell(args["session_id"], args.get("lines", 200))
        case "shell_kill":
            return await kill_shell(args["session_id"])
        case "shell_list":
            return await list_shells()
        case "list_files":
            return await _to_thread(
                list_dir,
                args.get("path", "."),
                args.get("recursive", False),
                args.get("max_entries", 500),
            )
        case "tree_view":
            return await tree(
                args.get("cwd", "."),
                args.get("depth", 3),
                args.get("max_entries", 500),
            )
        case "glob_search":
            return {
                "paths": await _to_thread(
                    glob_paths,
                    args["pattern"],
                    args.get("cwd", "."),
                    args.get("max_results", 500),
                )
            }
        case "grep_search":
            return await grep(
                args["query"],
                args.get("cwd", "."),
                args.get("glob"),
                args.get("regex", True),
                args.get("case_sensitive", True),
                args.get("max_results"),
            )
        case "read_file":
            return await _to_thread(
                read_text,
                args["path"],
                args.get("start_line"),
                args.get("end_line"),
                args.get("binary_preview"),
                args.get("binary_preview_bytes", 256),
            )
        case "read_many_files":
            return await _to_thread(
                _read_many_files_sync,
                args["paths"],
                args.get("start_line"),
                args.get("end_line"),
                args.get("binary_preview"),
                args.get("binary_preview_bytes", 256),
            )
        case "write_file":
            return await _to_thread(
                write_text,
                args["path"],
                args["content"],
                args.get("overwrite", True),
            )
        case "edit_file":
            return await _to_thread(
                edit_text,
                args["path"],
                args["old"],
                args["new"],
                args.get("replace_all", False),
            )
        case "multi_edit_file":
            return await _to_thread(
                multi_edit_text, args["path"], args["edits"]
            )
        case "delete_file_or_dir":
            return await _to_thread(
                delete_path, args["path"], args.get("recursive", False)
            )
        case "apply_patch":
            return await _apply_patch_text(args["patch"], args.get("cwd", "."))
        case _:
            raise ValueError(f"unsupported remote worker tool: {tool}")


def worker_capabilities() -> list[str]:
    """List tool categories available in the worker environment."""
    return ["shell", "persistent_shell", "files", "search", "python"]


def worker_info(workdir: str) -> dict[str, Any]:
    """Return worker identity, workspace, platform, Python, and capability metadata."""
    return {
        "hostname": socket.gethostname(),
        "user": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
        "cwd": os.getcwd(),
        "workdir": workdir,
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }


async def run_worker(
    server: str,
    invite: str,
    name: str | None = None,
    workdir: str | None = None,
    persist: bool = False,
) -> None:
    """Register with a server, poll for jobs, execute tools locally, and submit results until stopped."""
    workdir = str(Path(workdir or os.getcwd()).expanduser().resolve())
    os.environ.setdefault("LOCAL_SHELL_MCP_WORKSPACE_ROOT", workdir)
    os.environ.setdefault("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    from ..config.settings import clear_settings_cache

    clear_settings_cache()
    server = server.rstrip("/")
    async with httpx.AsyncClient(timeout=None) as client:
        register_payload = {
            "invite": invite,
            "name": name,
            "workdir": workdir,
            "capabilities": worker_capabilities(),
            "info": worker_info(workdir),
        }
        response = await client.post(
            f"{server}{REMOTE_API_PREFIX}/register",
            json=register_payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        token = data["token"]
        machine_name = data["name"]
        print("local-shell-mcp worker")
        print(f"Server:  {server}")
        print(f"Name:    {machine_name}")
        print(f"Workdir: {workdir}")
        print("Status: connected")
        print(
            "Keep this process running while ChatGPT should access this machine. Press Ctrl-C to disconnect.",
            flush=True,
        )
        headers = {"Authorization": f"Bearer {token}"}
        while True:
            poll = await client.post(
                f"{server}{REMOTE_API_PREFIX}/poll",
                headers=headers,
                json={},
                timeout=None,
            )
            poll.raise_for_status()
            payload = poll.json().get("data", {})
            job = payload.get("job")
            if not job:
                continue
            try:
                result = await execute_worker_tool(
                    job["tool"], dict(job.get("args") or {})
                )
                out = {"job_id": job["id"], "ok": True, "data": result}
            except Exception as exc:
                out = {
                    "job_id": job.get("id"),
                    **_handled_remote_exception(exc),
                }
            await client.post(
                f"{server}{REMOTE_API_PREFIX}/result",
                headers=headers,
                json=out,
                timeout=30,
            )


def add_worker_cli_args(parser: argparse.ArgumentParser) -> None:
    """Add remote-worker connection and lifecycle options to the shared CLI parser."""
    parser.add_argument("--server", required=True)
    parser.add_argument("--invite", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Reserved for future user-service installation",
    )


def run_worker_from_args(args: argparse.Namespace) -> None:
    """Run a remote worker from parsed CLI arguments."""
    asyncio.run(
        run_worker(
            args.server, args.invite, args.name, args.workdir, args.persist
        )
    )


def run_worker_cli(argv: list[str] | None = None) -> None:
    """Entry point for launching a standalone remote worker process."""
    parser = argparse.ArgumentParser(
        description="Connect this machine to a local-shell-mcp control server"
    )
    add_worker_cli_args(parser)
    args = parser.parse_args(argv)
    run_worker_from_args(args)
