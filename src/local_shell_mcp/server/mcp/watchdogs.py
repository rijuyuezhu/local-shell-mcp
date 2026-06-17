"""MCP tool audit and timeout watchdog helpers."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, Protocol, cast

from mcp.server.fastmcp import FastMCP

from ...audit import (
    audit,
    audit_tool_call_end,
    audit_tool_call_start,
    new_audit_call_id,
)
from ...ops.command_ops import tool_timeout_s
from ...tools.declarative import (
    mcp_handler_error_handler,
    mcp_handler_uses_envelope,
)
from ...tools.responses import handled_error


class AuditedMcpToolFn(Protocol):
    """Callable MCP tool wrapper marked after audit/watchdog installation."""

    __local_shell_mcp_audit_watchdog__: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...


class PublicToolTimeoutError(TimeoutError):
    """Signals that a public tool timed out and should return structured retry guidance instead of a generic failure."""

    pass


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
    """Return a wrapper that audits every MCP tool call and enforces the tool timeout."""

    mcp_envelope = mcp_handler_uses_envelope(original)
    mcp_error_handler = mcp_handler_error_handler(original)

    @wraps(original)
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
                original(*args, **kwargs), timeout=tool_timeout_s()
            )
        except TimeoutError:
            exc = PublicToolTimeoutError(
                f"{tool_name} exceeded {tool_timeout_s()} second tool timeout"
            )
            duration_ms = int((time.time() - start) * 1000)
            audit(
                "tool_timeout",
                tool=tool_name,
                timeout_s=tool_timeout_s(),
            )
            if mcp_error_handler is not None:
                payload = mcp_error_handler(exc, args, kwargs)
            elif mcp_envelope:
                payload = handled_error(exc)
            else:
                # raise directly -- the default behavior for connector
                payload = None
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
            if payload is None:
                raise exc from None
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

    if hasattr(original, "__signature__"):
        wrapped.__signature__ = original.__signature__  # type: ignore[attr-defined]
    audited = cast(AuditedMcpToolFn, wrapped)
    audited.__local_shell_mcp_audit_watchdog__ = True
    return audited


def install_mcp_tool_watchdogs(mcp: FastMCP) -> None:
    """Wrap FastMCP execution paths so public tools are audited and return structured timeout errors."""
    for tool in mcp._tool_manager._tools.values():
        if getattr(tool.fn, "__local_shell_mcp_audit_watchdog__", False):
            continue
        tool.fn = _mcp_tool_audit_watchdog_wrapper(tool.fn, tool.name)
