"""Typed structured outputs for connector-compatible workspace tools."""

from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """One connector-compatible search result card."""

    id: str = Field(description="Workspace result identifier passed to fetch.")
    title: str = Field(description="Human-readable result title.")
    url: str = Field(description="Connector URL for the result card.")


class SearchOutput(BaseModel):
    """Connector-compatible search response payload."""

    results: list[SearchResult] = Field(
        description="Connector-compatible result cards."
    )


class FetchOutput(BaseModel):
    """Connector-compatible fetched document payload."""

    id: str = Field(description="Fetched workspace result identifier.")
    title: str = Field(description="Human-readable fetched document title.")
    text: str = Field(description="Fetched document text content.")
    url: str = Field(description="Connector URL for the fetched document.")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional connector metadata for the fetched document.",
    )
