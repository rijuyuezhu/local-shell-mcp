"""Typed input annotations for todo tools."""

from typing import Annotated, Any

from pydantic import Field

ExpectedTodoRevisionArg = Annotated[
    int | None,
    Field(
        default=None,
        ge=0,
        description="Optional revision that must still be current before replacement.",
    ),
]


TodosArg = Annotated[
    list[dict[str, Any]],
    Field(
        description="Replacement todo list. Each item may include id, content, status, and priority."
    ),
]
