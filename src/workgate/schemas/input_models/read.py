"""Typed input annotations for the read tool."""

from typing import Annotated

from pydantic import Field

ReadPathArg = Annotated[
    str,
    Field(
        description=(
            "Single file or directory path with optional selector suffix. "
            "Examples: file.py, file.py:50, file.py:50-80, "
            "file.py:50+20, file.py:5-16,960-973, "
            "file.py:raw, file.py:50-80:raw, file.py:5-16,960-973:raw. "
            "Do not combine multiple files in one path; comma-separated ranges "
            "apply only within the same file."
        )
    ),
]
