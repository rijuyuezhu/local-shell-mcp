"""Secret scanning tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.secret_scan_ops import run_secret_scan
from ..base import HttpToolRoute, McpToolContext, ToolHandler, ToolRegistry
from ..responses import handled_error, ok_response


async def _secret_scan(args: dict[str, Any]) -> dict[str, Any]:
    return await run_secret_scan(
        args.get("cwd", "."), args.get("glob"), args.get("max_results", 200)
    )


SECRET_SCAN_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/secret_scan", "secret_scan"),
)

SECRET_SCAN_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "secret_scan": _secret_scan
}


class SecretScanToolRegistry(ToolRegistry):
    """Register secret scanning tools."""

    name = "secret_scan"

    def http_routes(self):
        return SECRET_SCAN_HTTP_ROUTES

    def http_handlers(self):
        return SECRET_SCAN_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_secret_scan_mcp(mcp, context)


def register_secret_scan_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register secret scan MCP tools."""
    protected_meta = context.protected_meta
    settings = context.settings

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Scan workspace text files for common secrets before commit, push, release, or sharing logs. "
            "Use as a precaution after editing configuration, credentials, CI, deployment, or documentation files. "
            f"glob can narrow the scan and max_results bounds findings; max_results is capped by max_grep_results={settings.max_grep_results}. Results are heuristic and do not prove the workspace is secret-free."
        ),
    )
    async def secret_scan(
        cwd: str = ".", glob: str | None = None, max_results: int = 200
    ) -> dict:
        """Scan workspace text files for common secrets."""
        try:
            return ok_response(await run_secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return handled_error(exc)
