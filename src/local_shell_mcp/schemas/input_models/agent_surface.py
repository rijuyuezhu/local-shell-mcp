"""Typed input annotations for high-level agent workflow tools."""

from typing import Annotated

from pydantic import Field

AgentReadPathArg = Annotated[
    str,
    Field(
        description=(
            "Path or path selector to read. Supported selectors include "
            "file.py:50, file.py:50-80, file.py:50+20, file.py:raw, "
            "and file.py:50-80:raw."
        )
    ),
]
