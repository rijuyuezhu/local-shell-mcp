import subprocess
import sys
from pathlib import Path

from local_shell_mcp.ui import contracts

_REPO = Path(__file__).parents[1]


def test_tui_executable_names_are_stable_for_both_platform_families() -> None:
    assert contracts.TUI_EXECUTABLE_BASENAME == "local-shell-mcp-tui"
    assert contracts.POSIX_TUI_EXECUTABLE_NAME == "local-shell-mcp-tui"
    assert contracts.WINDOWS_TUI_EXECUTABLE_NAME == "local-shell-mcp-tui.exe"
    assert (
        contracts.tui_executable_name(windows=False)
        == contracts.POSIX_TUI_EXECUTABLE_NAME
    )
    assert (
        contracts.tui_executable_name(windows=True)
        == contracts.WINDOWS_TUI_EXECUTABLE_NAME
    )
    assert contracts.tui_executable_name() == contracts.TUI_EXECUTABLE_NAME


def test_release_matrix_checker_uses_contract_without_project_install() -> None:
    completed = subprocess.run(
        [sys.executable, "-S", "scripts/validation/check-release-matrix.py"],
        cwd=_REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
