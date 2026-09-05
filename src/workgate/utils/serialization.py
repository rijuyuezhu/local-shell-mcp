"""JSON-compatible serialization helpers."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def to_jsonable(value: Any, *, exclude_none: bool = False) -> Any:
    """Return a recursively JSON-compatible representation of common app values."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).decode(errors="replace")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value, exclude_none=exclude_none)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=exclude_none)
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value), exclude_none=exclude_none)
    if isinstance(value, Mapping):
        return {
            str(key): to_jsonable(item, exclude_none=exclude_none)
            for key, item in value.items()
            if not (exclude_none and item is None)
        }
    if isinstance(value, Sequence):
        return [to_jsonable(item, exclude_none=exclude_none) for item in value]
    if isinstance(value, set | frozenset):
        return [to_jsonable(item, exclude_none=exclude_none) for item in value]
    return value
