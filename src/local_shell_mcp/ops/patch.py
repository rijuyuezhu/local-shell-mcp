"""Session-bound unified-diff and apply_patch envelope operations."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from ..patch_ops import git_apply_prefix, normalize_patch_text
from ..schemas.result_models.patch import ApplyPatchOutput
from ..tool_session.store import get_tool_session_store, resolve_session_path
from .utils.path import assert_text_input_size, relative_display
from .utils.remote_session import call_remote_session_tool
from .utils.temp_file import write_temp_text_file

APPLY_PATCH_PHASE_TIMEOUT_S = 20
APPLY_PATCH_WATCHDOG_TIMEOUT_S = 45
_APPLY_PATCH_MAX_OUTPUT_BYTES = 500_000


def _bounded_text(data: bytes, limit: int) -> tuple[str, bool]:
    """Decode one bounded subprocess stream and report tail truncation."""
    truncated = len(data) > limit
    payload = data[-limit:] if truncated else data
    return payload.decode("utf-8", errors="replace"), truncated


def _git_apply_args(
    git_bin: str,
    patch_path: Path,
    prefix: str | None,
    *,
    check: bool,
) -> list[str]:
    args = [git_bin, "apply"]
    if check:
        args.append("--check")
    if prefix:
        args.extend(["--directory", prefix])
    args.append(str(patch_path))
    return args


def _run_git_apply(
    args: list[str],
    cwd: Path,
    *,
    timeout_s: int = APPLY_PATCH_PHASE_TIMEOUT_S,
) -> dict[str, Any]:
    """Run one bounded git apply phase without shell interpolation."""
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
        stdout, stdout_truncated = _bounded_text(
            completed.stdout, _APPLY_PATCH_MAX_OUTPUT_BYTES
        )
        stderr, stderr_truncated = _bounded_text(
            completed.stderr, _APPLY_PATCH_MAX_OUTPUT_BYTES
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "timed_out": False,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "command": shlex.join(args),
            "stdout": stdout,
            "stderr": stderr,
            "truncated": stdout_truncated or stderr_truncated,
        }
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_truncated = _bounded_text(
            exc.stdout or b"", _APPLY_PATCH_MAX_OUTPUT_BYTES
        )
        stderr, stderr_truncated = _bounded_text(
            exc.stderr or b"", _APPLY_PATCH_MAX_OUTPUT_BYTES
        )
        message = f"git apply timed out after {timeout_s} seconds"
        stderr = f"{stderr}\n{message}".strip()
        return {
            "ok": False,
            "exit_code": None,
            "timed_out": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "command": shlex.join(args),
            "stdout": stdout,
            "stderr": stderr,
            "truncated": stdout_truncated or stderr_truncated,
        }


async def apply_patch_execute(
    patch: str,
    cwd: str = ".",
    session_id: str | None = None,
) -> ApplyPatchOutput:
    """Validate and apply one patch inside a local session workdir."""
    settings = get_settings()
    assert_text_input_size("patch", patch, settings.max_file_write_bytes)
    session = (
        get_tool_session_store().touch_session(session_id)
        if session_id is not None
        else None
    )
    resolved_cwd = (
        resolve_session_path(session, cwd, must_exist=True)
        if session is not None
        else Path(cwd).expanduser().resolve()
    )
    if not resolved_cwd.is_dir():
        raise NotADirectoryError(str(resolved_cwd))

    normalized = await asyncio.to_thread(
        normalize_patch_text, patch, str(resolved_cwd)
    )
    patch_path = await write_temp_text_file(
        "patch",
        normalized,
        filename_prefix="patch",
        suffix="diff",
    )
    prefix = await asyncio.to_thread(
        git_apply_prefix, settings.git_bin, str(resolved_cwd)
    )
    check_args = _git_apply_args(
        settings.git_bin, patch_path, prefix, check=True
    )
    check = await asyncio.to_thread(_run_git_apply, check_args, resolved_cwd)
    if not check["ok"]:
        return ApplyPatchOutput(
            **check,
            cwd=relative_display(resolved_cwd),
            patch_path=relative_display(patch_path),
            checked=False,
            applied=False,
        )

    apply_args = _git_apply_args(
        settings.git_bin, patch_path, prefix, check=False
    )
    result = await asyncio.to_thread(_run_git_apply, apply_args, resolved_cwd)
    return ApplyPatchOutput(
        **result,
        cwd=relative_display(resolved_cwd),
        patch_path=relative_display(patch_path),
        checked=True,
        applied=bool(result["ok"]),
    )


async def apply_patch_dispatch_execute(
    patch: str,
    cwd: str = ".",
    session_id: str | None = None,
) -> ApplyPatchOutput:
    """Dispatch apply_patch to a local or remote explicit session."""
    if session_id is None:
        return await apply_patch_execute(patch, cwd, session_id)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "apply_patch",
            {"patch": patch, "cwd": cwd},
        )
        return ApplyPatchOutput.model_validate(data)
    return await apply_patch_execute(patch, cwd, session_id)
