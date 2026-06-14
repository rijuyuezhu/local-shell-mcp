"""Shared public MCP/HTTP data models."""

from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Structured output schema for normal MCP tool response envelopes."""

    ok: bool = True
    message: str = ""
    data: Any = None
