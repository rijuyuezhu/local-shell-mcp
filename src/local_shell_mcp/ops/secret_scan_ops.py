"""Scan workspace text files for credential-like strings."""

import asyncio
import re
from typing import Any

from ..config.settings import get_settings
from .fs_ops import read_text
from .path_ops import relative_display, resolve_path

SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}


def run_secret_scan_sync(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> dict[str, Any]:
    """Scan workspace text files for credential-like strings while respecting limits."""
    settings = get_settings()
    max_results = max(1, min(max_results, settings.max_grep_results))
    base = resolve_path(cwd, must_exist=True)
    findings = []
    truncated_files = 0
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if glob and not path.match(glob):
            continue
        try:
            data = read_text(str(path))
        except Exception:
            continue
        if data.get("binary"):
            continue
        if data.get("truncated"):
            truncated_files += 1
        text = data.get("content") or ""
        for name, pattern in SECRET_PATTERNS.items():
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    {"type": name, "path": relative_display(path), "line": line}
                )
                if len(findings) >= max_results:
                    return {
                        "findings": findings,
                        "truncated": True,
                        "truncated_files": truncated_files,
                    }
    return {
        "findings": findings,
        "truncated": False,
        "truncated_files": truncated_files,
    }


async def run_secret_scan(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> dict[str, Any]:
    """Expose secret scanning through an async wrapper for tool handlers."""
    return await asyncio.to_thread(run_secret_scan_sync, cwd, glob, max_results)
