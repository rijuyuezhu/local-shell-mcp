"""Remote worker-side tool dispatch, process loop, and CLI helpers."""

import argparse
import asyncio
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

from ..utils.serialization import to_jsonable
from .constants import REMOTE_API_PREFIX
from .tool_specs import REMOTE_WORKER_TOOL_NAMES


def _handled_remote_exception(exc: Exception) -> dict[str, Any]:
    """Convert local helper failures into serializable worker-side error payloads."""
    return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


WORKER_TOOL_NAMES = REMOTE_WORKER_TOOL_NAMES


async def execute_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    """Dispatch a remote-worker tool call through the canonical local handler."""
    if tool not in WORKER_TOOL_NAMES:
        raise ValueError(f"unsupported remote worker tool: {tool}")
    from ..tools.local_invocations import call_local_tool

    return await call_local_tool(tool, args)


def _open_worker_request(
    request: urllib.request.Request, timeout: float | None
) -> bytes:
    """Open one worker HTTP request and return its response body."""
    if timeout is None:
        with urllib.request.urlopen(request) as response:
            return response.read()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _worker_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST a JSON worker request using only the standard library."""
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, headers=request_headers, method="POST"
    )
    try:
        body = _open_worker_request(request, timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"worker HTTP request failed with {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"worker HTTP request failed: {exc.reason}") from exc

    decoded = json.loads(body.decode())
    if not isinstance(decoded, dict):
        raise RuntimeError("worker HTTP response was not a JSON object")
    return cast(dict[str, Any], decoded)


def worker_capabilities() -> list[str]:
    """List tool categories available in the worker environment."""
    return [
        "shell",
        "persistent_shell",
        "files",
        "search",
        "python",
        "transfer",
    ]


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
    os.environ.setdefault("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "true")
    from ..config.settings import clear_settings_cache

    clear_settings_cache()
    server = server.rstrip("/")
    register_payload = {
        "invite": invite,
        "name": name,
        "workdir": workdir,
        "capabilities": worker_capabilities(),
        "info": worker_info(workdir),
    }
    body = await asyncio.to_thread(
        _worker_post_json,
        f"{server}{REMOTE_API_PREFIX}/register",
        register_payload,
        None,
        30,
    )
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
        poll_body = await asyncio.to_thread(
            _worker_post_json,
            f"{server}{REMOTE_API_PREFIX}/poll",
            {},
            headers,
            None,
        )
        payload = poll_body.get("data", {})
        job = payload.get("job") if isinstance(payload, dict) else None
        if not job:
            continue
        try:
            result = await execute_worker_tool(
                job["tool"], dict(job.get("args") or {})
            )
            out = {
                "job_id": job["id"],
                "ok": True,
                "data": to_jsonable(result),
            }
        except Exception as exc:
            out = {
                "job_id": job.get("id"),
                **_handled_remote_exception(exc),
            }
        await asyncio.to_thread(
            _worker_post_json,
            f"{server}{REMOTE_API_PREFIX}/result",
            out,
            headers,
            30,
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
