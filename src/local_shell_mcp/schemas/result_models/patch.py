"""Typed structured outputs for patch tools."""

from pydantic import Field

from .shell import CommandResult


class ApplyPatchOutput(CommandResult):
    """Result of checking and applying a unified diff."""

    patch_path: str = Field(
        description="Workspace-relative path to the temporary patch file used for git apply."
    )
