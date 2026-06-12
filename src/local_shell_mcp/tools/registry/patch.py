"""Patch application tool registry."""

from __future__ import annotations

from typing import Any

from ...ops.patch_ops import apply_patch_text
from ..definitions import DeclarativeToolRegistry, local_tool


@local_tool(http_method="POST", http_path="/tools/apply_patch")
async def apply_patch(patch: str, cwd: str = ".") -> dict[str, Any]:
    """Apply a unified diff using git apply. Use for larger edits, multi-file changes, file additions, and deletions when an exact patch is clearer than individual replacements. cwd controls where paths in the patch are resolved. This uses git apply as a patch engine; for git workflow commands such as status, diff, add, commit, or push, use run_shell_tool."""
    return await apply_patch_text(patch, cwd)


class PatchToolRegistry(DeclarativeToolRegistry):
    """Register patch application tools."""

    name = "patch"
    tools = (apply_patch,)
