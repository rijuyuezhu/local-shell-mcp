"""Serialization helpers for tool outputs used by audits and HTTP adapters."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel


def tool_output_jsonable(value: Any) -> Any:
    """Return a JSON-compatible representation of tool output values."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): tool_output_jsonable(item) for key, item in value.items()
        }
    if isinstance(value, str | bytes | bytearray):
        return value
    if isinstance(value, Sequence):
        return [tool_output_jsonable(item) for item in value]
    return value
