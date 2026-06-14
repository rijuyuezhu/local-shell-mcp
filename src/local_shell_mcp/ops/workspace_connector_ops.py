"""Connector-compatible workspace document search/fetch operations."""

import asyncio
import json
from typing import Any

from ..audit import audit
from .fs_ops import read_text
from .search_ops import grep


async def workspace_connector_search(query: str) -> str:
    """Return connector-compatible result cards for a workspace text search."""
    try:
        result = await grep(
            query,
            cwd=".",
            regex=False,
            case_sensitive=False,
            max_results=20,
        )
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
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


async def workspace_connector_fetch(id: str) -> str:
    """Return one connector-compatible document for a workspace result id."""
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
