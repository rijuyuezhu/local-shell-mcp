"""Remote worker-side tool dispatch, process loop, and CLI helpers."""

import argparse
import asyncio
import os
import socket
import sys
from pathlib import Path
from typing import Any

import httpx

from ..tools.local_invocations import call_local_tool
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
    return await call_local_tool(
        tool,
        args,
        audit_context={"remote_worker": True},
    )


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
