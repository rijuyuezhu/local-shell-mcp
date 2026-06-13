"""Environment info MCP tool registry."""

from ...config.settings import get_settings, safe_settings_dump
from ...ops.command_ops import run_shell
from ..declarative import DeclarativeToolRegistry


class EnvironmentToolRegistry(DeclarativeToolRegistry):
    """Register environment/probe tools."""

    name = "environment"


local_tool = EnvironmentToolRegistry.get_tool_decorator()


@local_tool(http_method="GET", http_path="/tools/environment_info")
async def environment_info() -> dict:
    """Return the active workspace, server settings, auth/policy state, and a small environment probe. Use this before planning tool-heavy work when you need to know the workspace root, auth/network policy, or basic runtime versions. This is read-only and intended for orientation, not for executing arbitrary commands."""
    settings = get_settings()
    result = await run_shell(
        "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
        cwd=".",
        timeout_s=10,
    )
    return {
        "settings": safe_settings_dump(settings),
        "probe": result.model_dump(),
    }
