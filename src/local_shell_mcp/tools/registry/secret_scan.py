"""Secret scanning tool registry."""

from ...ops.secret_scan import secret_scan_execute
from ...schemas.input_models.secret_scan import (
    SecretScanCwdArg,
    SecretScanGlobArg,
    SecretScanMaxResultsArg,
)
from ...schemas.result_models.secret_scan import SecretScanOutput
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class SecretScanToolRegistry(DeclarativeToolRegistry):
    """Register secret scanning tools."""

    name = "secret_scan"
    """Registry group name used for tool-surface organization."""


local_tool = SecretScanToolRegistry.get_tool_decorator()


def _secret_scan_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Scan workspace text files for common secret-like strings before commit, push, release, or sharing logs. Results are heuristic and do not prove the workspace is secret-free. Current max findings: {settings.max_grep_results}."""


@local_tool(
    http_method="POST",
    http_path="/tools/secret_scan",
    description=_secret_scan_description,
)
async def secret_scan(
    cwd: SecretScanCwdArg = ".",
    glob: SecretScanGlobArg = None,
    max_results: SecretScanMaxResultsArg = 200,
) -> SecretScanOutput:
    """Scan workspace text files for common secret-like strings."""
    return await secret_scan_execute(cwd, glob, max_results)
