from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops.patch import (
    _git_apply_args,
    apply_patch_dispatch_execute,
    apply_patch_execute,
)
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.local_handlers import local_tool_handlers


def _local_session(root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(root))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    return store.create_session(target="local", workdir=str(root)).session_id


@pytest.mark.asyncio
async def test_apply_patch_envelope_is_session_bound_and_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "sample.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    session_id = _local_session(tmp_path, monkeypatch)
    patch = """*** Begin Patch
*** Update File: sample.txt
@@
 one
-two
+TWO
*** Add File: added.txt
+new
*** End Patch
"""

    result = await apply_patch_execute(patch, ".", session_id)

    assert result.ok is True
    assert result.checked is True
    assert result.applied is True
    assert target.read_bytes() == b"one\r\nTWO\r\n"
    assert (tmp_path / "added.txt").read_text(encoding="utf-8") == "new\n"
    assert "--check" not in result.command


@pytest.mark.asyncio
async def test_apply_patch_uses_git_directory_from_nested_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    nested = repository / "nested"
    nested.mkdir(parents=True)
    target = nested / "file.txt"
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "add", "nested/file.txt"], cwd=repository, check=True
    )
    session_id = _local_session(nested, monkeypatch)

    result = await apply_patch_execute(
        """*** Begin Patch
*** Update File: file.txt
@@
-old
+new
*** End Patch
""",
        ".",
        session_id,
    )

    assert result.applied is True
    assert "--directory nested" in result.command
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_apply_patch_failed_preflight_does_not_modify_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("actual\n", encoding="utf-8")
    session_id = _local_session(tmp_path, monkeypatch)
    patch = """*** Begin Patch
*** Update File: sample.txt
@@
-missing
+replacement
*** End Patch
"""

    with pytest.raises(ValueError, match="does not match"):
        await apply_patch_execute(patch, ".", session_id)

    assert target.read_text(encoding="utf-8") == "actual\n"


@pytest.mark.asyncio
async def test_apply_patch_rejects_cwd_outside_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    session_id = _local_session(root, monkeypatch)

    with pytest.raises(ValueError, match="Path escapes workspace"):
        await apply_patch_execute(
            "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n",
            str(outside),
            session_id,
        )


@pytest.mark.asyncio
async def test_apply_patch_dispatches_remote_session(
    monkeypatch, tmp_path: Path
) -> None:
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    calls = []

    async def fake_call(remote_session, tool, args, timeout_s=None):
        calls.append((remote_session, tool, args, timeout_s))
        return {
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 1,
            "cwd": ".",
            "command": "git apply patch.diff",
            "stdout": "",
            "stderr": "",
            "truncated": False,
            "patch_path": ".local-shell-mcp/tmp/patch.diff",
            "checked": True,
            "applied": True,
        }

    monkeypatch.setattr(
        "local_shell_mcp.ops.patch.call_remote_session_tool", fake_call
    )
    result = await apply_patch_dispatch_execute(
        "diff --git a/a b/a\n", ".", session.session_id
    )

    assert result.applied is True
    assert len(calls) == 1
    called_session, tool, args, timeout_s = calls[0]
    assert called_session.session_id == session.session_id
    assert tool == "apply_patch"
    assert args == {"patch": "diff --git a/a b/a\n", "cwd": "."}
    assert timeout_s is None


def test_apply_patch_is_registered_and_uses_native_directory_argument() -> None:
    assert "apply_patch" in local_tool_handlers()
    args = _git_apply_args(
        "git", Path("patch file.diff"), "nested dir", check=True
    )
    assert args == [
        "git",
        "apply",
        "--check",
        "--directory",
        "nested dir",
        "patch file.diff",
    ]
