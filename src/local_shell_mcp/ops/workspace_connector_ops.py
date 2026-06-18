"""Connector-compatible workspace document search/fetch operations."""

import asyncio
from typing import Any

from ..audit import audit
from ..schemas.result_models.workspace_connector import (
    FetchOutput,
    SearchOutput,
    SearchResult,
)
from .files_ops import read_file_execute
from .search_ops import grep_search_execute


def search_error_output(
    exc: Exception, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> SearchOutput:
    """Return connector-compatible search output for MCP tool errors."""
    return SearchOutput(results=[])


def _fetch_id_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if "id" in kwargs:
        return str(kwargs["id"])
    if args:
        return str(args[0])
    return ""


def fetch_error_output(
    exc: Exception, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> FetchOutput:
    """Return connector-compatible fetch output for MCP tool errors."""
    id = _fetch_id_from_call(args, kwargs)
    return FetchOutput(
        id=id,
        title=id,
        text=f"Unable to fetch file: {type(exc).__name__}: {exc}",
        url=f"file:///workspace/{id}",
        metadata={
            "source": "workspace",
            "error": type(exc).__name__,
        },
    )


async def search_execute(query: str) -> SearchOutput:
    """Return connector-compatible result cards for a workspace text search."""
    try:
        result = await grep_search_execute(
            query,
            cwd=".",
            regex=False,
            case_sensitive=False,
            max_results=20,
        )
        seen: set[str] = set()
        rows: list[SearchResult] = []
        for match in result.matches:
            path = match.path
            if not path or path in seen:
                continue
            seen.add(path)
            line = match.line
            suffix = f":{line}" if line else ""
            rows.append(
                SearchResult(
                    id=path,
                    title=f"{path}{suffix}",
                    url=f"file:///workspace/{path}",
                )
            )
        return SearchOutput(results=rows)
    except Exception as exc:
        audit("tool_error", error=repr(exc))
        return search_error_output(exc, (), {"query": query})


async def fetch_execute(id: str) -> FetchOutput:
    """Return one connector-compatible document for a workspace result id."""
    try:
        read_result = await asyncio.to_thread(read_file_execute, id)
        data = read_result.model_dump(mode="json")
        path = str(data.get("path") or id)
        binary = bool(data.get("binary"))
        text = data.get("content")
        if binary:
            text = data.get("message", "Binary file omitted")
        return FetchOutput(
            id=path,
            title=path,
            text=str(text or ""),
            url=f"file:///workspace/{path}",
            metadata={
                "source": "workspace",
                "binary": binary,
                "bytes": data.get("bytes"),
            },
        )
    except Exception as exc:
        audit("tool_error", error=repr(exc))
        return fetch_error_output(exc, (), {"id": id})
