"""Patch application tool registry."""

from ...ops.patch import apply_patch_execute
from ...schemas.input_models.patch import PatchCwdArg, PatchTextArg
from ...schemas.input_models.session import SessionIdArg
from ...schemas.result_models.patch import ApplyPatchOutput
from ..declarative import DeclarativeToolRegistry


class PatchToolRegistry(DeclarativeToolRegistry):
    """Register patch application tools."""

    name = "patch"
    """Registry group name used for tool-surface organization."""


local_tool = PatchToolRegistry.get_tool_decorator()


@local_tool(
    http_method="POST",
    http_path="/tools/apply_patch",
    mcp_scopes=("shell:read", "shell:write", "git:write"),
)
async def apply_patch(
    session_id: SessionIdArg, patch: PatchTextArg, cwd: PatchCwdArg = "."
) -> ApplyPatchOutput:
    """Apply a unified diff inside an explicit agent/workspace session."""
    return await apply_patch_execute(patch, cwd, session_id)
