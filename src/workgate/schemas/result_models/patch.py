"""Typed structured outputs for patch application tools."""

from pydantic import BaseModel, Field


class ApplyPatchOutput(BaseModel):
    """Result of validating and applying a unified diff."""

    ok: bool = Field(
        description="Whether the final patch application succeeded."
    )
    exit_code: int | None = Field(
        description="git apply exit code, or null when execution timed out."
    )
    timed_out: bool = Field(
        default=False, description="Whether git apply exceeded its timeout."
    )
    duration_ms: int = Field(
        description="Elapsed time for the reported git phase."
    )
    cwd: str = Field(
        description="Resolved directory against which paths were applied."
    )
    command: str = Field(description="Human-readable git apply command.")
    stdout: str = Field(default="", description="Bounded standard output.")
    stderr: str = Field(default="", description="Bounded standard error.")
    truncated: bool = Field(
        default=False, description="Whether captured output was truncated."
    )
    patch_path: str = Field(
        description="Temporary normalized unified-diff file used by git apply."
    )
    checked: bool = Field(
        description="Whether the preflight git apply --check phase succeeded."
    )
    applied: bool = Field(
        description="Whether the patch was applied to the worktree."
    )
