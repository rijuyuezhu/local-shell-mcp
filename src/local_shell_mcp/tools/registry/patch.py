"""Patch application tool registry."""

from ...ops.patch import apply_patch_execute
from ...schemas.input_models.patch import PatchCwdArg, PatchTextArg
from ...schemas.result_models.patch import ApplyPatchOutput
from ..declarative import DeclarativeToolRegistry


class PatchToolRegistry(DeclarativeToolRegistry):
    """Register patch application tools."""

    name = "patch"


local_tool = PatchToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/apply_patch")
async def apply_patch(
    patch: PatchTextArg, cwd: PatchCwdArg = "."
) -> ApplyPatchOutput:
    """Apply a unified diff using git apply."""
    return await apply_patch_execute(patch, cwd)
