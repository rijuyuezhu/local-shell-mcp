"""Patch application tool registry."""

from ...ops.patch_ops import apply_patch_execute
from ..declarative import DeclarativeToolRegistry


class PatchToolRegistry(DeclarativeToolRegistry):
    """Register patch application tools."""

    name = "patch"


local_tool = PatchToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/apply_patch")
async def apply_patch(patch: str, cwd: str = ".") -> dict:
    """Apply a unified diff using git apply. Use for larger edits, multi-file changes, file additions, and deletions when an exact patch is clearer than individual replacements. cwd controls where paths in the patch are resolved. This uses git apply as a patch engine; for git workflow commands such as status, diff, add, commit, or push, use run_shell_command."""
    return await apply_patch_execute(patch, cwd)
