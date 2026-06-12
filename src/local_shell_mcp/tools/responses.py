"""Shared tool response envelopes and error conversion helpers."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from ..audit import audit
from ..ops.path_ops import missing_path_context
from ..responses import ok_envelope


def ok_response(data: Any = None, message: str = "") -> dict[str, Any]:
    """Wrap successful tool data in the response envelope used by MCP handlers."""
    return ok_envelope(data, message)


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
