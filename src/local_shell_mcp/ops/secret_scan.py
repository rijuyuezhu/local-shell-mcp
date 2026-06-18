"""Scan workspace text files for credential-like strings."""

import asyncio
import re

from ..config.settings import get_settings
from ..schemas.result_models.secret_scan import SecretFinding, SecretScanOutput
from .files import read_file_execute
from .utils.path import relative_display, resolve_path

SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}


def secret_scan_sync(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> SecretScanOutput:
    """Scan workspace text files for credential-like strings while respecting limits."""
    settings = get_settings()
    max_results = max(1, min(max_results, settings.max_grep_results))
    base = resolve_path(cwd, must_exist=True)
    findings: list[SecretFinding] = []
    truncated_files = 0
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if glob and not path.match(glob):
            continue
        try:
            data = read_file_execute(str(path))
        except Exception:
            continue
        if data.binary:
            continue
        if data.truncated:
            truncated_files += 1
        text = data.content or ""
        for name, pattern in SECRET_PATTERNS.items():
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    SecretFinding(
                        type=name, path=relative_display(path), line=line
                    )
                )
                if len(findings) >= max_results:
                    return SecretScanOutput(
                        findings=findings,
                        truncated=True,
                        truncated_files=truncated_files,
                    )
    return SecretScanOutput(
        findings=findings,
        truncated=False,
        truncated_files=truncated_files,
    )


async def secret_scan_execute(
    cwd: str = ".", glob: str | None = None, max_results: int = 200
) -> SecretScanOutput:
    """Expose secret scanning through an async wrapper for tool handlers."""
    return await asyncio.to_thread(secret_scan_sync, cwd, glob, max_results)
