"""Tokenized public file download link tool registry."""

import asyncio

from ...config.settings import Settings
from ...ops.downloads import (
    create_file_link_execute,
    list_file_links_execute,
    revoke_file_link_execute,
)
from ...schemas.input_models.downloads import (
    DownloadFilenameArg,
    DownloadPathArg,
    DownloadTokenArg,
    DownloadTtlArg,
    IncludeExpiredArg,
    MaxDownloadsArg,
)
from ...schemas.result_models.downloads import (
    CreateFileLinkOutput,
    ListFileLinksOutput,
    RevokeFileLinkOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class DownloadToolRegistry(DeclarativeToolRegistry):
    """Register protected tools for creating and managing download links."""

    name = "downloads"
    """Registry group name used for tool-surface organization."""


local_tool = DownloadToolRegistry.get_tool_decorator()


def _download_tools_enabled(settings: Settings) -> bool:
    return settings.file_download_enabled and settings.mode in {"http", "mcp"}


def _create_file_link_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Create a temporary tokenized HTTP download URL for one existing regular file in the controlled workspace/container. Use this when a user needs to download or open an artifact through a browser. The response includes a sensitive token and URL. Current TTL default/cap: {settings.file_download_default_ttl_s}/{settings.file_download_max_ttl_s} seconds. Current file-size cap: {settings.file_download_max_file_bytes} bytes, with 0 meaning no configured cap."""


@local_tool(
    http_method="POST",
    http_path="/tools/file_link/create",
    description=_create_file_link_description,
    enabled=_download_tools_enabled,
)
async def create_file_link(
    path: DownloadPathArg,
    ttl_s: DownloadTtlArg = None,
    filename: DownloadFilenameArg = None,
    max_downloads: MaxDownloadsArg = None,
) -> CreateFileLinkOutput:
    """Create a temporary tokenized browser download URL for one file."""
    return await asyncio.to_thread(
        create_file_link_execute, path, ttl_s, filename, max_downloads
    )


@local_tool(
    http_method="GET",
    http_path="/tools/file_link/list",
    enabled=_download_tools_enabled,
)
async def list_file_links(
    include_expired: IncludeExpiredArg = False,
) -> ListFileLinksOutput:
    """List tokenized file download links created by create_file_link."""
    return await asyncio.to_thread(list_file_links_execute, include_expired)


@local_tool(
    http_method="POST",
    http_path="/tools/file_link/revoke",
    enabled=_download_tools_enabled,
)
async def revoke_file_link(token: DownloadTokenArg) -> RevokeFileLinkOutput:
    """Revoke a tokenized file download link created by create_file_link."""
    return await asyncio.to_thread(revoke_file_link_execute, token)
