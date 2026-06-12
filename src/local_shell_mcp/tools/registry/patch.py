"""Patch application tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.patch_ops import apply_patch_text
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from ..responses import handled_error, ok_response


async def _apply_patch(args: dict[str, Any]) -> dict[str, Any]:
    return await apply_patch_text(args["patch"], args.get("cwd", "."))


PATCH_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/apply_patch", "apply_patch"),
)

PATCH_HTTP_HANDLERS: dict[str, ToolHandler] = {"apply_patch": _apply_patch}


class PatchToolRegistry(StaticHttpToolRegistry):
    """Register patch application tools."""

    name = "patch"

    routes = PATCH_HTTP_ROUTES
    handlers = PATCH_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_patch_mcp(mcp, context)


def register_patch_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register patch MCP tools."""
    protected_meta = context.protected_meta

    @mcp.tool(meta=protected_meta)
    async def apply_patch(patch: str, cwd: str = ".") -> dict:
        """Apply a unified diff using git apply. Use for larger edits, multi-file changes, file additions, and deletions when an exact patch is clearer than individual replacements. cwd controls where paths in the patch are resolved. This uses git apply as a patch engine; for git workflow commands such as status, diff, add, commit, or push, use run_shell_tool."""
        try:
            return ok_response(await apply_patch_text(patch, cwd))
        except Exception as exc:
            return handled_error(exc)
