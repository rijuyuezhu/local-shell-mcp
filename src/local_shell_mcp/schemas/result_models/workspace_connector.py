"""Typed structured outputs for connector-compatible workspace tools."""

from typing import Any

from pydantic import BaseModel


class SearchResult(BaseModel):
    """One connector-compatible search result card."""

    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    """Connector-compatible search response payload."""

    results: list[SearchResult]


class FetchOutput(BaseModel):
    """Connector-compatible fetched document payload."""

    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, Any] | None = None
