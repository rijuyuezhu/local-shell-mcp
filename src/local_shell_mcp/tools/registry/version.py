"""Version information MCP tool registry."""

from ...ops.version import version_info_execute
from ...schemas.result_models.version import VersionInfoOutput
from ..declarative import DeclarativeToolRegistry


class VersionToolRegistry(DeclarativeToolRegistry):
    """Register version-reporting tools."""

    name = "version"
    """Registry group name used for tool-surface organization."""


local_tool = VersionToolRegistry.get_tool_decorator()


@local_tool(
    http_method="GET",
    http_path="/tools/version",
    mcp_scopes=("shell:read",),
)
async def version() -> VersionInfoOutput:
    """Return package and runtime version information."""
    return version_info_execute()
