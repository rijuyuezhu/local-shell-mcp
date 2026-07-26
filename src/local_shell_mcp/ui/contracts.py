"""Stable cross-platform contracts shared by Human UI runtimes and releases."""

import os

TUI_EXECUTABLE_BASENAME = "local-shell-mcp-tui"
POSIX_TUI_EXECUTABLE_NAME = TUI_EXECUTABLE_BASENAME
WINDOWS_TUI_EXECUTABLE_NAME = f"{TUI_EXECUTABLE_BASENAME}.exe"


def tui_executable_name(*, windows: bool | None = None) -> str:
    """Return the stable OpenTUI executable filename for one platform family."""
    active_windows = os.name == "nt" if windows is None else windows
    return (
        WINDOWS_TUI_EXECUTABLE_NAME
        if active_windows
        else POSIX_TUI_EXECUTABLE_NAME
    )


TUI_EXECUTABLE_NAME = tui_executable_name()
