"""Typed structured outputs for version-reporting tools."""

from pydantic import BaseModel, Field


class VersionInfoOutput(BaseModel):
    """Package and runtime version information."""

    version: str = Field(description="Source package version.")
    package_version: str = Field(
        description="Installed distribution version when available."
    )
    python: str = Field(description="Python runtime version.")
    platform: str = Field(description="Platform descriptor for this process.")
