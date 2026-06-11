"""Shared helpers and metadata used by built-in tool registries."""

from __future__ import annotations

import asyncio
import json
import shlex
import time
import uuid
from contextlib import suppress
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...audit import (
    audit,
    audit_tool_call_end,
    audit_tool_call_start,
    new_audit_call_id,
)
from ...config.settings import get_settings
from ...ops.fs_ops import (
    missing_path_context,
    prune_temp_dir,
    read_text,
    relative_display,
    resolve_path,
    temp_dir,
)
from ...ops.shell_ops import (
    PUBLIC_RUN_SHELL_TIMEOUT_CAP_S,
    public_run_shell_timeout,
    run_shell,
)


def ok_response(data: Any = None, message: str = "") -> dict:
    """Wrap successful tool data in the response envelope used by MCP handlers."""
    return {"ok": True, "message": message, "data": data}


def handled_error(exc: Exception) -> dict:
    """Convert expected operational exceptions into user-visible tool error payloads."""
    audit("tool_error", error=repr(exc))
    if isinstance(exc, FileNotFoundError) and str(exc):
        with suppress(Exception):
            context = missing_path_context(str(exc))
            return ok_response(
                {
                    "status": "not_found",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    **context,
                },
                message=f"Path not found: {context['path']}",
            )
    return ok_response(
        {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        },
        message=f"Tool handled {type(exc).__name__}",
    )


async def to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    """Run blocking helpers in a worker thread while preserving async tool-handler flow."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _assert_text_input_size(
    label: str, text: str, limit: int | None = None
) -> None:
    """Reject oversized text payloads before they are written to disk or passed to patch tools."""
    settings = get_settings()
    max_bytes = limit or settings.max_file_write_bytes
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(
            f"Refusing {label} of {size} bytes; max is {max_bytes}"
        )


async def apply_patch_text(patch: str, cwd: str = ".") -> dict:
    """Apply a unified diff through git apply and return the command result envelope."""
    _assert_text_input_size("patch", patch)
    await to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, existok_response=True)
    await to_thread(patch_path.write_text, patch, encoding="utf-8")
    quoted = shlex.quote(str(patch_path))
    result = await run_shell(
        f"git apply --check {quoted} && git apply {quoted}",
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def run_python_script(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> dict:
    """Execute provided Python code from a temporary file and clean it up after completion."""
    _assert_text_input_size("Python script", code)
    await to_thread(prune_temp_dir)
    path = temp_dir() / f"script-{uuid.uuid4().hex}.py"
    path.parent.mkdir(parents=True, existok_response=True)
    await to_thread(path.write_text, code, encoding="utf-8")
    result = await run_shell(
        f"python3 {shlex.quote(str(path))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(path)}


SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}

OAUTH_SECURITY_SCHEMES = [
    {
        "type": "oauth2",
        "scopes": ["shell:read", "shell:write", "shell:execute", "git:write"],
    }
]
NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]
PUBLIC_TOOL_TIMEOUT_S = PUBLIC_RUN_SHELL_TIMEOUT_CAP_S


class PublicToolTimeoutError(TimeoutError):
    """Signals that a public tool timed out and should return structured retry guidance instead of a generic failure."""

    pass


def security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach security-scheme metadata to tools when HTTP OAuth mode requires authenticated calls."""
    return {"securitySchemes": schemes}


def _timeout_payload_for_tool(tool_name: str, exc: Exception) -> dict | str:
    """Build an actionable timeout payload that reports limits and next-step guidance for the failed tool."""
    if tool_name == "search":
        return json.dumps({"results": []}, ensure_ascii=False)
    if tool_name == "fetch":
        return json.dumps(
            {
                "id": "",
                "title": "",
                "text": str(exc),
                "url": "file:///workspace/",
                "metadata": {
                    "source": "workspace",
                    "error": type(exc).__name__,
                },
            },
            ensure_ascii=False,
        )
    return handled_error(exc)


def _mcp_tool_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Represent FastMCP positional/keyword arguments as the routed tool input payload."""
    if kwargs and not args:
        return kwargs
    if args and not kwargs:
        return list(args)
    if args or kwargs:
        return {"args": list(args), "kwargs": kwargs}
    return {}


def _mcp_tool_audit_watchdog_wrapper(original, tool_name: str):  # noqa: ANN001, ANN202
    """Return a wrapper that audits every MCP tool call and enforces the public timeout."""

    async def wrapped(*args, **kwargs):  # noqa: ANN002, ANN003
        call_id = new_audit_call_id()
        start = time.time()
        audit_tool_call_start(
            call_id=call_id,
            transport="mcp",
            tool=tool_name,
            input=_mcp_tool_input(args, kwargs),
        )
        try:
            result = await asyncio.wait_for(
                original(*args, **kwargs), timeout=PUBLIC_TOOL_TIMEOUT_S
            )
        except TimeoutError:
            exc = PublicToolTimeoutError(
                f"{tool_name} exceeded {PUBLIC_TOOL_TIMEOUT_S} second public tool timeout"
            )
            duration_ms = int((time.time() - start) * 1000)
            audit(
                "tool_timeout",
                tool=tool_name,
                timeout_s=PUBLIC_TOOL_TIMEOUT_S,
            )
            payload = _timeout_payload_for_tool(tool_name, exc)
            audit_tool_call_end(
                call_id=call_id,
                transport="mcp",
                tool=tool_name,
                ok=False,
                duration_ms=duration_ms,
                output=payload,
                error={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "repr": repr(exc),
                },
            )
            return payload
        except BaseException as exc:
            duration_ms = int((time.time() - start) * 1000)
            audit_tool_call_end(
                call_id=call_id,
                transport="mcp",
                tool=tool_name,
                ok=False,
                duration_ms=duration_ms,
                error={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "repr": repr(exc),
                },
            )
            raise
        duration_ms = int((time.time() - start) * 1000)
        audit_tool_call_end(
            call_id=call_id,
            transport="mcp",
            tool=tool_name,
            ok=True,
            duration_ms=duration_ms,
            output=result,
        )
        return result

    wrapped.__local_shell_mcp_audit_watchdog__ = True  # type: ignore[attr-defined]
    return wrapped


def install_mcp_tool_watchdogs(mcp: FastMCP) -> None:
    """Wrap FastMCP execution paths so public tools are audited and return structured timeout errors."""
    for tool in mcp._tool_manager._tools.values():  # noqa: SLF001
        if getattr(tool.fn, "__local_shell_mcp_audit_watchdog__", False):
            continue
        tool.fn = _mcp_tool_audit_watchdog_wrapper(tool.fn, tool.name)


def install_full_container_auto_approval_hints(mcp: FastMCP) -> None:
    """Patch generated tool schemas to advertise reduced confirmation needs in full-container mode."""
    if not get_settings().allow_full_container:
        return
    for tool in mcp._tool_manager._tools.values():  # noqa: SLF001
        if tool.name == "call_agent_mcp_tool" or tool.name.startswith(
            "agent_mcp__"
        ):
            continue
        if tool.annotations and tool.annotations.readOnlyHint:
            continue
        tool.annotations = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        )


def read_many_files_sync(
    paths: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = 256,
) -> dict:
    """Read many files for a tool call while preserving per-path success and error entries."""
    settings = get_settings()
    if len(paths) > settings.max_read_many_files:
        raise ValueError(
            f"Refusing to read {len(paths)} files; max is {settings.max_read_many_files}"
        )

    files = []
    total_content_bytes = 0
    for path in paths:
        item = read_text(
            path, start_line, end_line, binary_preview, binary_preview_bytes
        )
        content = item.get("content")
        if isinstance(content, str):
            total_content_bytes += len(content.encode("utf-8"))
        preview = item.get("preview")
        if isinstance(preview, str):
            total_content_bytes += len(preview.encode("utf-8"))
        if total_content_bytes > settings.max_read_many_total_bytes:
            raise ValueError(
                f"Refusing to return {total_content_bytes} bytes from read_many_files; "
                f"max is {settings.max_read_many_total_bytes}"
            )
        files.append(item)
    return {"files": files, "total_content_bytes": total_content_bytes}


def run_secret_scan_sync(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> dict:
    """Scan workspace text files for credential-like strings while respecting size, binary, and result limits."""
    import re

    settings = get_settings()
    max_results = max(1, min(max_results, settings.max_grep_results))
    base = resolve_path(cwd, must_exist=True)
    findings = []
    truncated_files = 0
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if glob and not path.match(glob):
            continue
        try:
            data = read_text(str(path))
        except Exception:
            continue
        if data.get("binary"):
            continue
        if data.get("truncated"):
            truncated_files += 1
        text = data.get("content") or ""
        for name, pattern in SECRET_PATTERNS.items():
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    {"type": name, "path": relative_display(path), "line": line}
                )
                if len(findings) >= max_results:
                    return {
                        "findings": findings,
                        "truncated": True,
                        "truncated_files": truncated_files,
                    }
    return {
        "findings": findings,
        "truncated": False,
        "truncated_files": truncated_files,
    }


async def run_secret_scan(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> dict:
    """Expose secret scanning through an async wrapper for MCP handlers."""
    return await to_thread(run_secret_scan_sync, cwd, glob, max_results)


def read_audit_tail_entries(lines: int = 100) -> dict:
    """Parse the recent audit-log tail into structured records, preserving malformed lines as raw entries."""
    settings = get_settings()
    path = settings.audit_log_path
    if not path.exists():
        return {"entries": []}

    line_limit = max(1, min(lines, 1000))
    max_bytes = max(1, settings.max_audit_tail_bytes)
    chunks: list[bytes] = []
    bytes_read = 0
    newline_count = 0
    with path.open("rb") as fh:
        fh.seek(0, 2)
        position = fh.tell()
        while (
            position > 0
            and bytes_read < max_bytes
            and newline_count <= line_limit
        ):
            read_size = min(8192, position, max_bytes - bytes_read)
            position -= read_size
            fh.seek(position)
            chunk = fh.read(read_size)
            chunks.append(chunk)
            bytes_read += len(chunk)
            newline_count += chunk.count(b"\n")

    content = (
        b"".join(reversed(chunks))
        .decode("utf-8", errors="replace")
        .splitlines()[-line_limit:]
    )
    entries = []
    for line in content:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line})
    return {
        "entries": entries,
        "bytes_read": bytes_read,
        "truncated_bytes": max(0, path.stat().st_size - bytes_read),
    }
