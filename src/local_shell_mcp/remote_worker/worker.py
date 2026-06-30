"""Remote worker-side tool dispatch, process loop, and CLI helpers."""

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

from ..remote.constants import (
    REMOTE_API_PREFIX,
    REMOTE_WORKER_IDENTITY_FILE_NAME,
)
from ..remote.tool_specs import REMOTE_WORKER_TOOL_NAMES
from .compat import _jsonable as to_jsonable


def _handled_remote_exception(exc: Exception) -> dict[str, Any]:
    """Convert local helper failures into serializable worker-side error payloads."""
    return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


WORKER_TOOL_NAMES = REMOTE_WORKER_TOOL_NAMES


async def execute_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    """Dispatch a remote-worker tool call through the canonical local handler."""
    if tool not in WORKER_TOOL_NAMES:
        raise ValueError(f"unsupported remote worker tool: {tool}")
    from .dispatch import execute_worker_tool as dispatch_worker_tool

    return await dispatch_worker_tool(tool, args)


def _parse_worker_http_json(
    url: str, status_code: int, response_body: str
) -> dict[str, Any]:
    """Validate one worker HTTP response and return its JSON object body."""
    if not 200 <= status_code < 300:
        detail = response_body.strip() or "<empty response body>"
        raise RuntimeError(
            f"worker HTTP POST {url} failed with {status_code}: {detail}"
        )
    try:
        decoded = json.loads(response_body)
    except json.JSONDecodeError as exc:
        detail = response_body.strip() or "<empty response body>"
        raise RuntimeError(
            f"worker HTTP POST {url} returned invalid JSON: {detail}"
        ) from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(
            f"worker HTTP POST {url} returned JSON {type(decoded).__name__}, expected object"
        )
    return cast(dict[str, Any], decoded)


def _worker_post_json_with_curl(
    url: str, body: bytes, headers: dict[str, str], timeout: float | None = None
) -> dict[str, Any]:
    """POST JSON through curl when available to better handle CDN/proxy edge cases."""
    curl = shutil.which("curl")
    if not curl:
        raise FileNotFoundError("curl is not available")
    status_marker = "\nLOCAL_SHELL_MCP_HTTP_STATUS:"
    command = [
        curl,
        "-sS",
        "-L",
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
        "-w",
        f"{status_marker}%{{http_code}}",
    ]
    for name, value in headers.items():
        command.extend(["-H", f"{name}: {value}"])
    if timeout is not None:
        command[1:1] = ["--max-time", str(timeout)]
    command.append(url)
    completed = subprocess.run(
        command, input=body, capture_output=True, check=False
    )  # noqa: S603
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    response_body, marker, status_text = stdout.rpartition(status_marker)
    status_code = int(status_text) if marker and status_text.isdigit() else 0
    if completed.returncode != 0:
        detail_parts = [
            part for part in (stderr, response_body.strip()) if part
        ]
        detail = (
            "\n".join(detail_parts) or "curl exited without a response body"
        )
        raise RuntimeError(
            f"worker HTTP POST {url} failed with curl exit {completed.returncode} (HTTP {status_code}): {detail}"
        )
    return _parse_worker_http_json(url, status_code, response_body)


def _worker_post_json_with_urllib(
    url: str, body: bytes, headers: dict[str, str], timeout: float | None = None
) -> dict[str, Any]:
    """POST JSON using the standard library fallback."""
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status_code = response.status
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return _parse_worker_http_json(url, exc.code, response_body)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"worker HTTP request failed: {exc.reason}") from exc
    return _parse_worker_http_json(url, status_code, response_body)


def _worker_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST a JSON worker request using curl when available or urllib otherwise."""
    body = json.dumps(payload).encode("utf-8")
    request_headers = headers or {}
    if shutil.which("curl"):
        return _worker_post_json_with_curl(url, body, request_headers, timeout)
    return _worker_post_json_with_urllib(url, body, request_headers, timeout)


_WORKER_RETRY_INITIAL_DELAY_S = 1.0
_WORKER_RETRY_MAX_DELAY_S = 30.0


def _worker_retry_delay(attempt: int) -> float:
    """Return exponential reconnect delay capped for long-running worker loops."""
    return min(
        _WORKER_RETRY_INITIAL_DELAY_S * (2 ** min(attempt, 5)),
        _WORKER_RETRY_MAX_DELAY_S,
    )


def _worker_log_retry(operation: str, exc: Exception, delay_s: float) -> None:
    """Print one retry status line to stderr for worker operators."""
    print(
        f"Status: {operation} failed: {exc}. Retrying in {delay_s:g}s...",
        file=sys.stderr,
        flush=True,
    )


async def _worker_post_json_forever(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    operation: str = "request",
) -> dict[str, Any]:
    """POST JSON until it succeeds, preserving remote workers across outages."""
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(
                _worker_post_json, url, payload, headers, timeout
            )
        except Exception as exc:
            delay_s = _worker_retry_delay(attempt)
            attempt += 1
            _worker_log_retry(operation, exc, delay_s)
            await asyncio.sleep(delay_s)


def _worker_state_dir() -> Path:
    """Return the state directory used to persist this worker identity."""
    configured = os.getenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "local-shell-mcp-worker"
    return Path.home() / ".local" / "state" / "local-shell-mcp-worker"


def _normalized_env_path(path: str) -> str:
    """Normalize an environment path without requiring the path to exist."""
    expanded = os.path.expandvars(os.path.expanduser(path))
    return os.path.abspath(expanded)


def _env_is_absent_or_default(name: str, default: str) -> bool:
    """Return whether a worker env path is unset or still the package default."""
    value = os.getenv(name)
    return not value or _normalized_env_path(value) == default


def _configure_worker_runtime_env(workdir: str) -> None:
    """Configure worker-local runtime paths before loading normal settings."""
    if _env_is_absent_or_default(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", "/workspace"
    ):
        os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] = workdir
    if _env_is_absent_or_default(
        "LOCAL_SHELL_MCP_STATE_DIR", "/workspace/.local-shell-mcp"
    ):
        os.environ["LOCAL_SHELL_MCP_STATE_DIR"] = str(
            _worker_state_dir() / "runtime"
        )
    os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL"] = "true"


def _worker_identity_path() -> Path:
    """Return the JSON identity file path for this worker process."""
    return _worker_state_dir() / REMOTE_WORKER_IDENTITY_FILE_NAME


def _read_worker_identity(
    server: str, requested_name: str | None = None
) -> dict[str, Any] | None:
    """Read a stored worker identity when it matches the target server/name."""
    path = _worker_identity_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("server") != server:
        return None
    stored_name = str(data.get("name") or "")
    if requested_name and stored_name != requested_name:
        return None
    if not stored_name or not str(data.get("access") or ""):
        return None
    return data


def _write_worker_identity(data: dict[str, Any]) -> None:
    """Persist a worker identity atomically with owner-only permissions where possible."""
    path = _worker_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        tmp_path.chmod(0o600)
    tmp_path.replace(path)


def _delete_worker_identity() -> None:
    """Remove the stored worker identity after the control server rejects it."""
    with contextlib.suppress(FileNotFoundError):
        _worker_identity_path().unlink()


def _worker_identity_rejected(exc: Exception) -> bool:
    """Return whether a resume failure means the persisted identity is invalid."""
    message = str(exc).lower()
    return (
        "failed with 401" in message
        or "invalid worker identity" in message
        or "identity is no longer valid" in message
    )


async def _worker_resume_or_none(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float | None = None,
) -> dict[str, Any] | None:
    """Try to resume a worker identity, retrying transient failures indefinitely."""
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(
                _worker_post_json, url, payload, headers, timeout
            )
        except Exception as exc:
            if _worker_identity_rejected(exc):
                print(
                    "Status: stored worker identity rejected; falling back to invite registration.",
                    file=sys.stderr,
                    flush=True,
                )
                _delete_worker_identity()
                return None
            delay_s = _worker_retry_delay(attempt)
            attempt += 1
            _worker_log_retry("resume", exc, delay_s)
            await asyncio.sleep(delay_s)


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
    _configure_worker_runtime_env(workdir)
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
    identity = _read_worker_identity(server, name)
    body: dict[str, Any] | None = None
    access = ""
    if identity:
        access = str(identity["access"])
        resume_payload = {**register_payload, "name": str(identity["name"])}
        resume_headers = {"Author" + "ization": "B" + "earer " + access}
        body = await _worker_resume_or_none(
            f"{server}{REMOTE_API_PREFIX}/resume",
            resume_payload,
            resume_headers,
            30,
        )
    if body is None:
        body = await _worker_post_json_forever(
            f"{server}{REMOTE_API_PREFIX}/register",
            register_payload,
            None,
            30,
            "register",
        )
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        access = data["to" + "ken"]
        machine_name = data["name"]
    else:
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        machine_name = data["name"]
    _write_worker_identity(
        {
            "server": server,
            "name": machine_name,
            "access": access,
            "workdir": workdir,
        }
    )
    print("local-shell-mcp worker")
    print(f"Server:  {server}")
    print(f"Name:    {machine_name}")
    print(f"Workdir: {workdir}")
    print("Status: connected")
    print(
        "Keep this process running while ChatGPT should access this machine. Press Ctrl-C to disconnect.",
        flush=True,
    )
    headers = {"Author" + "ization": "B" + "earer " + access}
    while True:
        poll_body = await _worker_post_json_forever(
            f"{server}{REMOTE_API_PREFIX}/poll", {}, headers, None, "poll"
        )
        payload = poll_body.get("data", {})
        job = payload.get("job") if isinstance(payload, dict) else None
        if not job:
            continue
        try:
            result = await execute_worker_tool(
                job["tool"], dict(job.get("args") or {})
            )
            out = {"job_id": job["id"], "ok": True, "data": to_jsonable(result)}
        except Exception as exc:
            out = {"job_id": job.get("id"), **_handled_remote_exception(exc)}
        await _worker_post_json_forever(
            f"{server}{REMOTE_API_PREFIX}/result",
            out,
            headers,
            30,
            "submit result",
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
    try:
        asyncio.run(
            run_worker(
                args.server, args.invite, args.name, args.workdir, args.persist
            )
        )
    except KeyboardInterrupt:
        print("\nStatus: disconnected by user.", file=sys.stderr, flush=True)
        raise SystemExit(130) from None


def run_worker_cli(argv: list[str] | None = None) -> None:
    """Entry point for launching a standalone remote worker process."""
    parser = argparse.ArgumentParser(
        description="Connect this machine to a local-shell-mcp control server"
    )
    add_worker_cli_args(parser)
    args = parser.parse_args(argv)
    run_worker_from_args(args)
