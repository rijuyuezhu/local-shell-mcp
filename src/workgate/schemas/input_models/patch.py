"""Typed input annotations for patch application tools."""

from typing import Annotated

from pydantic import Field

PatchTextArg = Annotated[
    str,
    Field(
        description="A standard unified diff or an apply_patch envelope beginning with '*** Begin Patch'. Paths resolve inside cwd and the explicit session workdir."
    ),
]

PatchCwdArg = Annotated[
    str,
    Field(
        description="Directory inside the explicit session workdir against which patch paths are resolved. Defaults to the session workdir."
    ),
]
