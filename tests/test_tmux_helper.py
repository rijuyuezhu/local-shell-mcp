from __future__ import annotations

from pathlib import Path

import pytest

from local_shell_mcp import tmux_helper


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("x86_64", "linux-x86_64"),
        ("amd64", "linux-x86_64"),
        ("x64", "linux-x86_64"),
        ("aarch64", "linux-aarch64"),
        ("arm64", "linux-aarch64"),
    ],
)
def test_platform_tag_normalizes_linux_architectures(
    machine: str, expected: str
):
    assert (
        tmux_helper._platform_tag(system="Linux", machine=machine) == expected
    )


def test_platform_tag_rejects_unsupported_platforms():
    assert tmux_helper._platform_tag(system="Darwin", machine="arm64") is None
    assert tmux_helper._platform_tag(system="Linux", machine="riscv64") is None


def _install_helper(root: Path, tag: str = "linux-x86_64") -> Path:
    helper = root / "helpers" / tag / "tmux"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"tmux")
    helper.chmod(0o755)
    return helper


def test_bundled_tmux_path_returns_matching_regular_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    helper = _install_helper(tmp_path)
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    assert tmux_helper.bundled_tmux_path(package_root=tmp_path) == helper


def test_bundled_tmux_path_repairs_user_execute_bit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    helper = _install_helper(tmp_path)
    access_results = iter([False, True])
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    monkeypatch.setattr(
        tmux_helper.os, "access", lambda *_: next(access_results)
    )
    assert tmux_helper.bundled_tmux_path(package_root=tmp_path) == helper
    assert helper.stat().st_mode & 0o100


def test_bundled_tmux_path_rejects_missing_unsupported_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: None)
    assert tmux_helper.bundled_tmux_path(package_root=tmp_path) is None
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    assert tmux_helper.bundled_tmux_path(package_root=tmp_path) is None
    target = _install_helper(tmp_path, "target")
    link = tmp_path / "helpers" / "linux-x86_64" / "tmux"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    assert tmux_helper.bundled_tmux_path(package_root=tmp_path) is None


def test_bundled_tmux_path_handles_chmod_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    helper = _install_helper(tmp_path)
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    monkeypatch.setattr(tmux_helper.os, "access", lambda *_: False)
    monkeypatch.setattr(
        Path, "chmod", lambda *_: (_ for _ in ()).throw(OSError())
    )
    assert tmux_helper.bundled_tmux_path(package_root=tmp_path) is None
    assert helper.exists()


def test_resolve_tmux_prefers_system_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        tmux_helper.shutil, "which", lambda value: "/usr/bin/tmux"
    )
    selected = tmux_helper.resolve_tmux("tmux")
    assert selected == tmux_helper.TmuxSelection(
        "/usr/bin/tmux", "system", "tmux"
    )


def test_resolve_tmux_preserves_explicit_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _install_helper(tmp_path)
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda value: None)
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    selected = tmux_helper.resolve_tmux(
        "/missing/custom-tmux", package_root=tmp_path
    )
    assert selected.path is None
    assert selected.source == "configured"
    with pytest.raises(RuntimeError, match="Configured tmux executable"):
        tmux_helper.require_tmux("/missing/custom-tmux", package_root=tmp_path)


def test_resolve_tmux_falls_back_to_bundled_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    helper = _install_helper(tmp_path)
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda value: None)
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    selected = tmux_helper.require_tmux("", package_root=tmp_path)
    assert selected == tmux_helper.TmuxSelection(str(helper), "bundled", "tmux")


def test_require_tmux_reports_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda value: None)
    monkeypatch.setattr(tmux_helper, "bundled_tmux_path", lambda **kwargs: None)
    with pytest.raises(RuntimeError, match="tmux is unavailable"):
        tmux_helper.require_tmux("tmux")


def test_resolve_tmux_reads_settings_and_reports_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
):
    class Settings:
        tmux_bin = "configured-tmux"

    monkeypatch.setattr(tmux_helper, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        tmux_helper.shutil,
        "which",
        lambda value: "/opt/tmux" if value == "configured-tmux" else None,
    )
    assert tmux_helper.tmux_backend_info() == {
        "available": True,
        "source": "configured",
        "path": "/opt/tmux",
        "bundled_version": None,
    }


def test_bundled_diagnostics_include_version(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        tmux_helper,
        "resolve_tmux",
        lambda configured=None: tmux_helper.TmuxSelection(
            "/bundle/tmux", "bundled", "tmux"
        ),
    )
    assert tmux_helper.tmux_backend_info()["bundled_version"] == "3.5a"


@pytest.mark.asyncio
async def test_shell_tmux_uses_resolved_executable(
    monkeypatch: pytest.MonkeyPatch,
):
    from local_shell_mcp.ops import shell

    expected = object()
    calls: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        shell,
        "require_tmux",
        lambda: tmux_helper.TmuxSelection(
            "/bundle path/tmux", "bundled", "tmux"
        ),
    )

    async def fake_run_shell(command: str, cwd: str, timeout_s: int):
        calls.append((command, cwd, timeout_s))
        return expected

    monkeypatch.setattr(shell, "run_shell", fake_run_shell)
    assert await shell.tmux(["list-sessions"], timeout_s=7) is expected
    assert calls == [("'/bundle path/tmux' list-sessions", ".", 7)]
