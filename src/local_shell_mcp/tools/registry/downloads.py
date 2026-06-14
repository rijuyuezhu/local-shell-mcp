"""Tokenized public file download link tool registry."""

import asyncio
from typing import Any

from ...ops.download_ops import (
    create_share_link,
    list_share_links,
    revoke_share_link,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class DownloadToolRegistry(DeclarativeToolRegistry):
    """Register protected tools for creating and managing download links."""

    name = "downloads"


local_tool = DownloadToolRegistry.get_tool_decorator()


def _create_file_link_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Create a temporary tokenized HTTP download URL for one existing regular file in the controlled workspace/container. "
        "Use this only when a user needs to download or open an artifact through a browser; for agent-side inspection, prefer read_file or read_many_files instead. "
        "Parameters: path is required and must resolve to an existing file, not a directory; "
        f"ttl_s is the link lifetime in seconds, defaults to file_download_default_ttl_s={settings.file_download_default_ttl_s}, and is capped by file_download_max_ttl_s={settings.file_download_max_ttl_s}; "
        "filename optionally overrides the browser download name and any path components are stripped; "
        f"max_downloads defaults to file_download_default_max_downloads={settings.file_download_default_max_downloads}; max_downloads=0 means unlimited downloads until expiry. "
        f"file_download_max_file_bytes={settings.file_download_max_file_bytes} is the file-size cap, with 0 meaning no configured cap. "
        "The response includes the share token and URL; treat both as sensitive and revoke the link when it should no longer be usable."
    )


def _list_file_links_description(_: McpToolContext) -> str:
    return (
        "List tokenized file download links created by create_file_link. "
        "Use this to audit what is currently shareable, find a token before revoking it, or include expired links for cleanup/debugging. "
        "Parameter: include_expired defaults to false and hides links that are already expired or exhausted; set it true when you need historical entries. "
        "Each entry summarizes the token, URL, source display path, browser filename, expiry, download count, and max_downloads limit."
    )


def _revoke_file_link_description(_: McpToolContext) -> str:
    return (
        "Revoke a tokenized file download link created by create_file_link. "
        "Use this when a shared artifact should stop being browser-accessible before its TTL or download limit expires. "
        "Parameter: token is the share token returned by create_file_link or list_file_links, not the full URL. "
        "The operation is safe to call for missing or already-expired tokens; the response reports whether a link was actually removed."
    )


@local_tool(
    http_method="POST",
    http_path="/tools/file_link/create",
    description=_create_file_link_description,
)
async def create_file_link(
    path: str,
    ttl_s: int | None = None,
    filename: str | None = None,
    max_downloads: int | None = None,
) -> dict[str, Any]:
    """Create a temporary tokenized browser download URL for one file."""
    return await asyncio.to_thread(
        create_share_link, path, ttl_s, filename, max_downloads
    )


@local_tool(
    http_method="GET",
    http_path="/tools/file_link/list",
    description=_list_file_links_description,
)
async def list_file_links(include_expired: bool = False) -> dict[str, Any]:
    """List generated tokenized file download URLs."""
    return await asyncio.to_thread(list_share_links, include_expired)


@local_tool(
    http_method="POST",
    http_path="/tools/file_link/revoke",
    description=_revoke_file_link_description,
)
async def revoke_file_link(token: str) -> dict[str, Any]:
    """Revoke a generated tokenized file download URL."""
    return await asyncio.to_thread(revoke_share_link, token)
