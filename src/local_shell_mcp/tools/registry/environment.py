"""Environment info MCP tool registry."""

from ...ops.environment import environment_info_execute
from ...schemas.result_models.environment import EnvironmentInfoOutput
from ..declarative import DeclarativeToolRegistry


class EnvironmentToolRegistry(DeclarativeToolRegistry):
    """Register environment/probe tools."""

    name = "environment"


local_tool = EnvironmentToolRegistry.get_tool_decorator()


@local_tool(http_method="GET", http_path="/tools/environment_info")
async def environment_info() -> EnvironmentInfoOutput:
    """Return the active workspace, server settings, auth/policy state, and a small environment probe. Use this before planning tool-heavy work when you need to know the workspace root, auth/network policy, or basic runtime versions. This is read-only and intended for orientation, not for executing arbitrary commands."""
    return await environment_info_execute()
