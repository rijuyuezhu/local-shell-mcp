"""Typed structured outputs for secret scanning tools."""

from pydantic import BaseModel, Field


class SecretFinding(BaseModel):
    """One heuristic secret finding."""

    type: str = Field(description="Heuristic pattern name that matched.")
    path: str = Field(
        description="Workspace-relative file path containing the finding."
    )
    line: int = Field(description="1-based line number containing the finding.")


class SecretScanOutput(BaseModel):
    """Heuristic workspace secret-scan result."""

    findings: list[SecretFinding] = Field(
        description="Returned heuristic secret findings."
    )
    truncated: bool = Field(
        description="Whether the finding list was truncated by the result limit."
    )
    truncated_files: int = Field(
        description="Number of scanned files whose text was truncated before scanning."
    )
