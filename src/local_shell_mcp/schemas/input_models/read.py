"""Typed input annotations for the read tool."""

from typing import Annotated

from pydantic import Field

ReadPathArg = Annotated[
    str,
    Field(
        description=(
            "File or directory path with optional selector suffix. "
            "Examples: file.py, file.py:50, file.py:50-80, "
            "file.py:50+20, file.py:raw, file.py:50-80:raw."
        )
    ),
]
