"""Scan workspace text files for credential-like strings."""

import asyncio
import re

from ..config.settings import get_settings
from ..schemas.result_models.secret_scan import SecretFinding, SecretScanOutput
from ..tool_session.store import get_tool_session_store, resolve_session_path
from .files import read_file_execute
from .utils.path import relative_display, resolve_path
from .utils.remote_session import call_remote_session_tool

SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}


def secret_scan_sync(
    cwd: str = ".",
    glob: str | None = None,
    max_results: int = 200,
    session_id: str | None = None,
) -> SecretScanOutput:
    """Scan workspace text files for credential-like strings while respecting limits."""
    settings = get_settings()
    max_results = max(1, min(max_results, settings.max_grep_results))
    session = (
        get_tool_session_store().touch_session(session_id)
        if session_id is not None
        else None
    )
    base = (
        resolve_session_path(session, cwd, must_exist=True)
        if session is not None
        else resolve_path(cwd, must_exist=True)
    )
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
        if data.truncated:
            truncated_files += 1
        text = data.content
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
    cwd: str = ".",
    glob: str | None = None,
    max_results: int = 200,
    session_id: str | None = None,
) -> SecretScanOutput:
    """Expose secret scanning through an async wrapper for tool handlers."""
    if session_id is not None:
        session = get_tool_session_store().touch_session(session_id)
        if session.target == "remote":
            data = await call_remote_session_tool(
                session,
                "secret_scan",
                {
                    "cwd": cwd,
                    "glob": glob,
                    "max_results": max_results,
                },
            )
            return SecretScanOutput.model_validate(data)
    return await asyncio.to_thread(
        secret_scan_sync, cwd, glob, max_results, session_id
    )
