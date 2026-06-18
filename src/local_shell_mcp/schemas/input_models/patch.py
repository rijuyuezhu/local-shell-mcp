"""Typed input annotations for patch tools."""

from typing import Annotated

from pydantic import Field

PatchTextArg = Annotated[
    str,
    Field(
        description="Unified diff text to validate and apply with git apply."
    ),
]
PatchCwdArg = Annotated[
    str,
    Field(
        description="Working directory where patch paths are resolved. Relative paths resolve inside the configured workspace."
    ),
]
