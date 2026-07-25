from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from local_shell_mcp.ui import contracts

_REPO = Path(__file__).parents[1]
_GENERATOR = _REPO / "scripts" / "generate-tui-executable-contract.py"
_GENERATED_TYPESCRIPT = (
    _REPO / "ui-opentui" / "scripts" / "executable-contract.ts"
)
_COMPILE_TYPESCRIPT = _REPO / "ui-opentui" / "scripts" / "compile-tui.ts"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_tui_executable_contract",
        _GENERATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_generated_bun_contract_matches_python_source_of_truth() -> None:
    generator = _load_generator()
    assert _GENERATED_TYPESCRIPT.read_text(encoding="utf-8") == (
        generator.render_contract()
    )

    compile_text = _COMPILE_TYPESCRIPT.read_text(encoding="utf-8")
    assert 'from "./executable-contract"' in compile_text
    assert '"local-shell-mcp-tui"' not in compile_text
    assert '"local-shell-mcp-tui.exe"' not in compile_text


def test_python_executable_name_literal_has_one_owner() -> None:
    package_root = _REPO / "src" / "local_shell_mcp"
    owners = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
        if "local-shell-mcp-tui" in path.read_text(encoding="utf-8")
    }
    assert owners == {"ui/contracts.py"}


def test_release_matrix_checker_uses_contract_without_project_install() -> None:
    completed = subprocess.run(
        [sys.executable, "-S", "scripts/validation/check-release-matrix.py"],
        cwd=_REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
