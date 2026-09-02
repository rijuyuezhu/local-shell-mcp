"""Dependency-light serialization for the source-only remote worker."""

import dataclasses
import enum
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def to_jsonable(value: Any, *, exclude_none: bool = False) -> Any:
    """Return a recursively JSON-compatible value without third-party imports."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).decode(errors="replace")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value, exclude_none=exclude_none)
    if (
        not isinstance(value, type)
        and hasattr(value, "model_dump")
        and callable(value.model_dump)
    ):
        return value.model_dump(mode="json", exclude_none=exclude_none)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(dataclasses.asdict(value), exclude_none=exclude_none)
    if isinstance(value, Mapping):
        return {
            str(key): to_jsonable(item, exclude_none=exclude_none)
            for key, item in value.items()
            if not (exclude_none and item is None)
        }
    if isinstance(value, Sequence) and not isinstance(
        value, str | bytes | bytearray
    ):
        return [to_jsonable(item, exclude_none=exclude_none) for item in value]
    if isinstance(value, set | frozenset):
        return [to_jsonable(item, exclude_none=exclude_none) for item in value]
    return value
