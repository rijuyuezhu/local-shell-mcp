"""Filesystem/search MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .local import register_filesystem_mcp


class FilesystemToolRegistry(ToolRegistry):
    """Register filesystem, search, patch, and audit tools."""

    name = "filesystem"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {
            "list_files",
            "tree_view",
            "glob_search",
            "grep_search",
            "read_file",
            "read_many_files",
            "write_file",
            "edit_file",
            "multi_edit_file",
            "delete_file_or_dir",
            "apply_patch",
            "secret_scan",
            "audit_tail",
        }
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_filesystem_mcp(mcp, context)
