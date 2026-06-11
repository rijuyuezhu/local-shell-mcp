"""Shell MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ...ops.shell_ops import (
    kill_shell,
    list_shells,
    public_run_shell,
    read_shell,
    send_shell,
    start_shell,
)
from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .common import handled_error, ok_response, run_python_script


class ShellToolRegistry(ToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {
            "run_shell_tool",
            "run_python_tool",
            "shell_start",
            "shell_send",
            "shell_read",
            "shell_kill",
            "shell_list",
        }
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_shell_mcp(mcp, context)


def register_shell_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    oauth_meta = context.oauth_meta

    @mcp.tool(meta=oauth_meta)
    async def run_shell_tool(
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
    ) -> dict:
        """Run a shell command in the controlled container. This is the primary coding-agent tool."""
        try:
            return ok_response(
                (
                    await public_run_shell(
                        command, cwd, timeout_s, max_output_bytes
                    )
                ).model_dump()
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def run_python_tool(
        code: str, cwd: str = ".", timeout_s: int = 60
    ) -> dict:
        """Write Python code to a temporary file and execute it."""
        try:
            return ok_response(await run_python_script(code, cwd, timeout_s))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_start(
        cwd: str = ".", name: str | None = None, command: str | None = None
    ) -> dict:
        """Start a persistent tmux-backed shell session."""
        try:
            return ok_response(await start_shell(cwd, name, command))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_send(
        session_id: str, input_text: str, enter: bool = True
    ) -> dict:
        """Send input to a persistent shell session."""
        try:
            return ok_response(await send_shell(session_id, input_text, enter))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_read(session_id: str, lines: int = 200) -> dict:
        """Read recent output from a persistent shell session."""
        try:
            return ok_response(await read_shell(session_id, lines))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_kill(session_id: str) -> dict:
        """Kill a persistent shell session."""
        try:
            return ok_response(await kill_shell(session_id))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_list() -> dict:
        """List persistent shell sessions."""
        try:
            return ok_response(await list_shells())
        except Exception as exc:
            return handled_error(exc)
