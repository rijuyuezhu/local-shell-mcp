"""Secret scanning tool registry."""

from __future__ import annotations

from ...ops.secret_scan_ops import run_secret_scan
from ..base import McpToolContext
from ..definitions import DeclarativeToolRegistry, local_tool


def _secret_scan_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Scan workspace text files for common secrets before commit, push, release, or sharing logs. "
        "Use as a precaution after editing configuration, credentials, CI, deployment, or documentation files. "
        f"glob can narrow the scan and max_results bounds findings; max_results is capped by max_grep_results={settings.max_grep_results}. Results are heuristic and do not prove the workspace is secret-free."
    )


@local_tool(
    http_method="POST",
    http_path="/tools/secret_scan",
    description=_secret_scan_description,
)
async def secret_scan(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> dict:
    """Scan workspace text files for common secrets."""
    return await run_secret_scan(cwd, glob, max_results)


class SecretScanToolRegistry(DeclarativeToolRegistry):
    """Register secret scanning tools."""

    name = "secret_scan"
    tools = (secret_scan,)
