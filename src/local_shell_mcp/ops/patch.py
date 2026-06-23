"""Apply patch operations through bounded shell execution."""

import shlex

from ..schemas.result_models.patch import ApplyPatchOutput
from ..tool_session.store import get_tool_session_store, resolve_session_path
from .shell import run_shell
from .utils.path import relative_display
from .utils.remote_session import call_remote_session_tool
from .utils.temp_file import write_temp_text_file


async def apply_patch_execute(
    patch: str, cwd: str = ".", session_id: str | None = None
) -> ApplyPatchOutput:
    """Apply a unified diff through git apply and return the command result envelope."""
    session = (
        get_tool_session_store().touch_session(session_id)
        if session_id is not None
        else None
    )
    if session is not None and session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "apply_patch",
            {
                "patch": patch,
                "cwd": cwd,
            },
        )
        return ApplyPatchOutput.model_validate(data)

    resolved_cwd = (
        str(resolve_session_path(session, cwd, must_exist=True))
        if session is not None
        else cwd
    )
    patch_path = await write_temp_text_file("patch", patch, "patch", "diff")
    quoted = shlex.quote(str(patch_path))
    result = await run_shell(
        f"git apply --check {quoted} && git apply {quoted}",
        cwd=resolved_cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return ApplyPatchOutput.model_validate(
        {
            **result.model_dump(),
            "patch_path": relative_display(patch_path),
        }
    )
