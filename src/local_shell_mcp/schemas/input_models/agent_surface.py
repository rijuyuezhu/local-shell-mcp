"""Typed input annotations for high-level agent workflow tools."""

from typing import Annotated

from pydantic import Field

AgentReadPathArg = Annotated[
    str,
    Field(
        description=(
            "File or directory path with optional oh-my-pi-style selector. "
            "Examples: file.py, file.py:50, file.py:50-80, "
            "file.py:50+20, file.py:raw, file.py:50-80:raw."
        )
    ),
]
