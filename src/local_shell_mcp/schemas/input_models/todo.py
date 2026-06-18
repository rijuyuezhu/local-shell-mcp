"""Typed input annotations for todo tools."""

from typing import Annotated, Any

from pydantic import Field

TodosArg = Annotated[
    list[dict[str, Any]],
    Field(
        description="Replacement todo list. Each item may include id, content, status, and priority."
    ),
]
