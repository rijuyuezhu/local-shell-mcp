"""Tokenized public file download link tool registry."""

import asyncio
from typing import Any

from ...ops.download_ops import (
    create_share_link,
    list_share_links,
    revoke_share_link,
)
from ..declarative import DeclarativeToolRegistry


class DownloadToolRegistry(DeclarativeToolRegistry):
    """Register protected tools for creating and managing download links."""

    name = "downloads"


local_tool = DownloadToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/file_link/create")
async def create_file_link(
    path: str,
    ttl_s: int | None = None,
    filename: str | None = None,
    max_downloads: int | None = None,
) -> dict[str, Any]:
    """Create a temporary browser-accessible download URL for a file. max_downloads=0 means unlimited until expiry."""
    return await asyncio.to_thread(
        create_share_link, path, ttl_s, filename, max_downloads
    )


@local_tool(http_method="GET", http_path="/tools/file_link/list")
async def list_file_links(include_expired: bool = False) -> dict[str, Any]:
    """List generated file download URLs."""
    return await asyncio.to_thread(list_share_links, include_expired)


@local_tool(http_method="POST", http_path="/tools/file_link/revoke")
async def revoke_file_link(token: str) -> dict[str, Any]:
    """Revoke a generated file download URL."""
    return await asyncio.to_thread(revoke_share_link, token)
