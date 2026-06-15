"""Tokenized public file download link tool registry."""

import asyncio
from typing import Any

from ...config.settings import Settings
from ...ops.download_ops import (
    create_file_link_execute,
    list_file_links_execute,
    revoke_file_link_execute,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class DownloadToolRegistry(DeclarativeToolRegistry):
    """Register protected tools for creating and managing download links."""

    name = "downloads"


local_tool = DownloadToolRegistry.get_tool_decorator()


def _download_tools_enabled(settings: Settings) -> bool:
    return settings.file_download_enabled and settings.mode in {"http", "mcp"}


def _create_file_link_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Create a temporary tokenized HTTP download URL for one existing regular file in the controlled workspace/container. Use this when a user needs to download or open an artifact through a browser. For agent-side file inspection, use read_file or read_many_files. Parameters: path is required and must resolve to an existing file, not a directory; ttl_s is the link lifetime in seconds. Defaults: ttl_s defaults to file_download_default_ttl_s={settings.file_download_default_ttl_s} and is capped by file_download_max_ttl_s={settings.file_download_max_ttl_s}. Parameters: filename optionally overrides the browser download name and any path components are stripped. Limits: max_downloads defaults to file_download_default_max_downloads={settings.file_download_default_max_downloads}; max_downloads=0 means unlimited downloads until expiry. Limits: file_download_max_file_bytes={settings.file_download_max_file_bytes} is the file-size cap, with 0 meaning no configured cap. The response includes the share token and URL; treat both as sensitive and revoke the link when it should no longer be usable."""


@local_tool(
    http_method="POST",
    http_path="/tools/file_link/create",
    description=_create_file_link_description,
    enabled=_download_tools_enabled,
)
async def create_file_link(
    path: str,
    ttl_s: int | None = None,
    filename: str | None = None,
    max_downloads: int | None = None,
) -> dict[str, Any]:
    """Create a temporary tokenized browser download URL for one file."""
    return await asyncio.to_thread(
        create_file_link_execute, path, ttl_s, filename, max_downloads
    )


@local_tool(
    http_method="GET",
    http_path="/tools/file_link/list",
    enabled=_download_tools_enabled,
)
async def list_file_links(include_expired: bool = False) -> dict[str, Any]:
    """List tokenized file download links created by create_file_link. Use this to audit what is currently shareable, find a token before revoking it, or include expired links for cleanup/debugging. Parameter: include_expired defaults to false and hides links that are already expired or exhausted; set it true when you need historical entries. Each entry summarizes the token, URL, source display path, browser filename, expiry, download count, and max_downloads limit."""
    return await asyncio.to_thread(list_file_links_execute, include_expired)


@local_tool(
    http_method="POST",
    http_path="/tools/file_link/revoke",
    enabled=_download_tools_enabled,
)
async def revoke_file_link(token: str) -> dict[str, Any]:
    """Revoke a tokenized file download link created by create_file_link. Use this when a shared artifact should stop being browser-accessible before its TTL or download limit expires. Parameter: token is the share token returned by create_file_link or list_file_links, not the full URL. The operation is safe to call for missing or already-expired tokens; the response reports whether a link was actually removed."""
    return await asyncio.to_thread(revoke_file_link_execute, token)
