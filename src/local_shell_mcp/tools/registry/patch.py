"""Patch application tool registry."""

from ...ops.patch_ops import apply_patch_execute
from ..declarative import DeclarativeToolRegistry
from ..inputs.patch import PatchCwdArg, PatchTextArg
from ..outputs.patch import ApplyPatchOutput


class PatchToolRegistry(DeclarativeToolRegistry):
    """Register patch application tools."""

    name = "patch"


local_tool = PatchToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/apply_patch")
async def apply_patch(
    patch: PatchTextArg, cwd: PatchCwdArg = "."
) -> ApplyPatchOutput:
    """Apply a unified diff using git apply."""
    return ApplyPatchOutput.model_validate(
        await apply_patch_execute(patch, cwd)
    )
