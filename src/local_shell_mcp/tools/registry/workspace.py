"""Workspace connector MCP tool registry."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...audit import audit
from ...ops.fs_ops import read_text
from ...ops.search_ops import grep
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from ..responses import to_thread


async def _search(args: dict[str, Any]) -> str:
    try:
        result = await grep(
            args["query"],
            cwd=".",
            regex=False,
            case_sensitive=False,
            max_results=20,
        )
        seen: set[str] = set()
        rows = []
        for match in result.get("matches", []):
            path = match.get("path")
            if not path or path in seen:
                continue
            seen.add(path)
            line = match.get("line")
            suffix = f":{line}" if line else ""
            rows.append(
                {
                    "id": path,
                    "title": f"{path}{suffix}",
                    "url": f"file:///workspace/{path}",
                }
            )
        return json.dumps({"results": rows}, ensure_ascii=False)
    except Exception as exc:
        audit("tool_error", error=repr(exc))
        return json.dumps({"results": []}, ensure_ascii=False)


async def _fetch(args: dict[str, Any]) -> str:
    file_id = args["id"]
    try:
        data = await to_thread(read_text, file_id)
        path = data.get("path") or file_id
        binary = bool(data.get("binary"))
        return json.dumps(
            {
                "id": path,
                "title": path,
                "text": data.get("content")
                if not binary
                else data.get("message", "Binary file omitted"),
                "url": f"file:///workspace/{path}",
                "metadata": {
                    "source": "workspace",
                    "binary": binary,
                    "bytes": data.get("bytes"),
                },
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        audit("tool_error", error=repr(exc))
        return json.dumps(
            {
                "id": file_id,
                "title": file_id,
                "text": f"Unable to fetch file: {type(exc).__name__}: {exc}",
                "url": f"file:///workspace/{file_id}",
                "metadata": {
                    "source": "workspace",
                    "error": type(exc).__name__,
                },
            },
            ensure_ascii=False,
        )


WORKSPACE_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/search", "search"),
    HttpToolRoute("POST", "/tools/fetch", "fetch"),
)

WORKSPACE_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "search": _search,
    "fetch": _fetch,
}


class WorkspaceConnectorToolRegistry(StaticHttpToolRegistry):
    """Register ChatGPT connector-compatible workspace tools."""

    name = "workspace_connector"

    routes = WORKSPACE_HTTP_ROUTES
    handlers = WORKSPACE_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_workspace_connector_mcp(mcp, context)


def register_workspace_connector_mcp(
    mcp: FastMCP, context: McpToolContext
) -> None:
    """Register MCP tools for this tool group."""
    read_only_tool = context.read_only_tool
    connector_meta = context.connector_meta

    @mcp.tool(annotations=read_only_tool, meta=connector_meta)
    async def search(query: str) -> str:
        """Search workspace text files and return ChatGPT connector-compatible search results. Use this when a connector-style client needs file result ids rather than raw ripgrep matches. The search is case-insensitive literal text, limited to concise file-level results; use grep_search for regex searches, line matches, globs, or larger code-navigation tasks."""
        return await _search({"query": query})

    @mcp.tool(annotations=read_only_tool, meta=connector_meta)
    async def fetch(id: str) -> str:
        """Fetch a workspace file by id returned from search and format it as a ChatGPT connector document. Use only after search has returned an id. For coding work, prefer read_file because it supports line ranges, binary previews, and richer diagnostics."""
        return await _fetch({"id": id})
