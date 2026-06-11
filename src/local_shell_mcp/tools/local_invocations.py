"""Shared local tool invocation helpers used by HTTP adapters."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from typing import Any

from ..audit import (
    audit_tool_call_end,
    audit_tool_call_start,
    new_audit_call_id,
)
from .base import ToolHandler
from .discovery import discover_tool_registries


@lru_cache(maxsize=1)
def local_tool_handlers() -> Mapping[str, ToolHandler]:
    """Collect canonical local invocation handlers from discovered registries."""
    handlers: dict[str, ToolHandler] = {}
    for registry in discover_tool_registries():
        for tool_name, handler in registry.http_handlers().items():
            if tool_name in handlers:
                raise ValueError(f"Duplicate local tool handler: {tool_name}")
            handlers[tool_name] = handler
    return handlers


def _jsonable_dataclass(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


async def call_local_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    audit_context: dict[str, Any] | None = None,
) -> Any:
    """Invoke a local tool by canonical MCP tool name and audit the routed call."""
    try:
        handler = local_tool_handlers()[tool_name]
    except KeyError as exc:
        raise KeyError(f"Unknown local tool: {tool_name}") from exc

    payload = args or {}
    context = audit_context or {}
    call_id = new_audit_call_id()
    start = time.time()
    audit_tool_call_start(
        call_id=call_id,
        transport="http",
        tool=tool_name,
        input=payload,
        principal=_jsonable_dataclass(context.get("principal")),
        context={
            k: _jsonable_dataclass(v)
            for k, v in context.items()
            if k != "principal"
        },
    )
    try:
        result = await handler(payload)
    except BaseException as exc:
        duration_ms = int((time.time() - start) * 1000)
        audit_tool_call_end(
            call_id=call_id,
            transport="http",
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
        transport="http",
        tool=tool_name,
        ok=True,
        duration_ms=duration_ms,
        output=result,
    )
    return result
