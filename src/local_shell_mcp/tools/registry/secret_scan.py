"""Secret scanning tool registry."""

from typing import Any

from ...ops.secret_scan_ops import secret_scan_execute
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class SecretScanToolRegistry(DeclarativeToolRegistry):
    """Register secret scanning tools."""

    name = "secret_scan"


local_tool = SecretScanToolRegistry.get_tool_decorator()


def _secret_scan_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Scan workspace text files for common secrets before commit, push, release, or sharing logs. Use as a precaution after editing configuration, credentials, CI, deployment, or documentation files. Parameters: glob can narrow the scan and max_results bounds findings. Limits: max_results is capped by max_grep_results={settings.max_grep_results}. Results are heuristic and do not prove the workspace is secret-free."""


@local_tool(
    http_method="POST",
    http_path="/tools/secret_scan",
    description=_secret_scan_description,
)
async def secret_scan(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> dict[str, Any]:
    """Scan workspace text files for common secrets."""
    return await secret_scan_execute(cwd, glob, max_results)
