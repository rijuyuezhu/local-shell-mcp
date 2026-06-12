"""Workspace connector MCP tool registry."""

from __future__ import annotations

import asyncio
import json

from ...audit import audit
from ...ops.fs_ops import read_text
from ...ops.search_ops import grep
from ..definitions import DeclarativeToolRegistry


class WorkspaceConnectorToolRegistry(DeclarativeToolRegistry):
    """Register ChatGPT connector-compatible workspace tools."""

    name = "workspace_connector"


local_tool = WorkspaceConnectorToolRegistry.get_tool_decorator()


@local_tool(
    http_method="POST",
    http_path="/tools/search",
    meta="connector",
    annotations="read_only",
    mcp_envelope=False,
)
async def search(query: str) -> str:
    """Search workspace text files and return ChatGPT connector-compatible search results. Use this when a connector-style client needs file result ids rather than raw ripgrep matches. The search is case-insensitive literal text, limited to concise file-level results; use grep_search for regex searches, line matches, globs, or larger code-navigation tasks."""
    try:
        result = await grep(
            query,
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


@local_tool(
    http_method="POST",
    http_path="/tools/fetch",
    meta="connector",
    annotations="read_only",
    mcp_envelope=False,
)
async def fetch(id: str) -> str:
    """Fetch a workspace file by id returned from search and format it as a ChatGPT connector document. Use only after search has returned an id. For coding work, prefer read_file because it supports line ranges, binary previews, and richer diagnostics."""
    try:
        data = await asyncio.to_thread(read_text, id)
        path = data.get("path") or id
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
                "id": id,
                "title": id,
                "text": f"Unable to fetch file: {type(exc).__name__}: {exc}",
                "url": f"file:///workspace/{id}",
                "metadata": {
                    "source": "workspace",
                    "error": type(exc).__name__,
                },
            },
            ensure_ascii=False,
        )
