"""Shared helpers and metadata used by built-in tool registries."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Protocol, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...audit import (
    audit,
    audit_tool_call_end,
    audit_tool_call_start,
    new_audit_call_id,
)
from ...config.settings import get_settings
from ...ops.fs_ops import missing_path_context
from ...ops.shell_ops import public_tool_timeout_s


def ok_response(data: Any = None, message: str = "") -> dict[str, Any]:
    """Wrap successful tool data in the response envelope used by MCP handlers."""
    return {"ok": True, "message": message, "data": data}


def handled_error(exc: Exception) -> dict[str, Any]:
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


async def to_thread(func, *args, **kwargs):
    """Run blocking helpers in a worker thread while preserving async tool-handler flow."""
    return await asyncio.to_thread(func, *args, **kwargs)


OAUTH_SECURITY_SCHEMES = [
    {
        "type": "oauth2",
        "scopes": ["shell:read", "shell:write", "shell:execute"],
    }
]
NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]


class AuditedMcpToolFn(Protocol):
    """Callable MCP tool wrapper marked after audit/watchdog installation."""

    __local_shell_mcp_audit_watchdog__: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...


class PublicToolTimeoutError(TimeoutError):
    """Signals that a public tool timed out and should return structured retry guidance instead of a generic failure."""

    pass


def security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach security-scheme metadata to tools when HTTP OAuth mode requires authenticated calls."""
    return {"securitySchemes": schemes}


def _timeout_payload_for_tool(
    tool_name: str, exc: Exception
) -> dict[str, Any] | str:
    """Build an actionable timeout payload that reports limits and next-step guidance for the failed tool."""
    match tool_name:
        case "search":
            return json.dumps({"results": []}, ensure_ascii=False)
        case "fetch":
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
        case _:
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


def _mcp_tool_audit_watchdog_wrapper(
    original: Callable[..., Awaitable[Any]], tool_name: str
) -> AuditedMcpToolFn:
    """Return a wrapper that audits every MCP tool call and enforces the public timeout."""

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
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
                original(*args, **kwargs), timeout=public_tool_timeout_s()
            )
        except TimeoutError:
            exc = PublicToolTimeoutError(
                f"{tool_name} exceeded {public_tool_timeout_s()} second public tool timeout"
            )
            duration_ms = int((time.time() - start) * 1000)
            audit(
                "tool_timeout",
                tool=tool_name,
                timeout_s=public_tool_timeout_s(),
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

    audited = cast(AuditedMcpToolFn, wrapped)
    audited.__local_shell_mcp_audit_watchdog__ = True
    return audited


def install_mcp_tool_watchdogs(mcp: FastMCP) -> None:
    """Wrap FastMCP execution paths so public tools are audited and return structured timeout errors."""
    for tool in mcp._tool_manager._tools.values():
        if getattr(tool.fn, "__local_shell_mcp_audit_watchdog__", False):
            continue
        tool.fn = _mcp_tool_audit_watchdog_wrapper(tool.fn, tool.name)


def install_full_container_auto_approval_hints(mcp: FastMCP) -> None:
    """Patch local tool schemas to advertise reduced MCP client confirmation needs.

    These are client-facing hints only. They do not change server-side
    authentication, authorization, workspace boundaries, command policy, or audit
    behavior, and they intentionally do not mark mutating tools as read-only.
    """
    settings = get_settings()
    if not (
        settings.allow_full_container or settings.relaxed_client_tool_hints
    ):
        return
    for tool in mcp._tool_manager._tools.values():
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
