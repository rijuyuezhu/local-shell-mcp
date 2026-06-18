"""Typed structured outputs for environment tools."""

from typing import Any

from pydantic import BaseModel, Field

from .shell import RunShellCommandOutput


class EnvironmentInfoOutput(BaseModel):
    """Workspace, runtime, policy, and environment probe information."""

    settings: dict[str, Any] = Field(
        description="Safe server settings with secrets redacted, including workspace, auth, limits, and policy configuration."
    )
    probe: RunShellCommandOutput = Field(
        description="Bounded shell probe showing basic OS, user, working directory, Python, and git information."
    )
