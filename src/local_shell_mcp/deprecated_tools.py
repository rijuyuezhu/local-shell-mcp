"""Non-enumerated tombstones for tools removed from older MCP snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

DEPRECATED_TOOL_HELP_URL = (
    "https://github.com/rijuyuezhu/local-shell-mcp/issues"
)


@dataclass(frozen=True, slots=True)
class DeprecatedTool:
    """Describe a removed tool and the current tool that replaces it."""

    replacement: str
    """Current tool name that supersedes the removed tool."""
    removed_in: str = "3.0.0"
    """First package version where the old name was unavailable."""
    note: str = ""
    """Optional fork-specific migration guidance."""


_REMOTE_SESSION_NOTE = (
    "Create a remote session with session_start(target='remote', machine=...) first, "
    "then call the replacement tool with that session_id."
)

DEPRECATED_TOOLS: dict[str, DeprecatedTool] = {
    "version_info": DeprecatedTool("version"),
    "environment_info": DeprecatedTool("version"),
    "read_file": DeprecatedTool("read"),
    "read_many_files": DeprecatedTool("read"),
    "grep_search": DeprecatedTool("search"),
    "edit_file": DeprecatedTool("edit_lines"),
    "multi_edit_file": DeprecatedTool("hashline_edit"),
    "run_shell_tool": DeprecatedTool("bash"),
    "run_python_tool": DeprecatedTool("run_python_code"),
    "shell_start": DeprecatedTool("bash"),
    "shell_send": DeprecatedTool("send_persistent_shell_input"),
    "shell_read": DeprecatedTool("read_persistent_shell_output"),
    "shell_kill": DeprecatedTool("kill_persistent_shell"),
    "shell_list": DeprecatedTool("list_persistent_shells"),
    "job_start": DeprecatedTool("job"),
    "job_list": DeprecatedTool("job"),
    "job_tail": DeprecatedTool("job"),
    "job_stop": DeprecatedTool("job"),
    "job_retry": DeprecatedTool("job"),
    "transfer_path": DeprecatedTool("session_copy"),
    "git_clone_tool": DeprecatedTool("bash"),
    "git_status_tool": DeprecatedTool("bash"),
    "git_diff_tool": DeprecatedTool("bash"),
    "git_log_tool": DeprecatedTool("bash"),
    "git_checkout_tool": DeprecatedTool("bash"),
    "git_fetch_tool": DeprecatedTool("bash"),
    "git_pull_tool": DeprecatedTool("bash"),
    "git_add_tool": DeprecatedTool("bash"),
    "git_commit_tool": DeprecatedTool("bash"),
    "git_push_tool": DeprecatedTool("bash"),
    "git_show_tool": DeprecatedTool("bash"),
    "git_reset_tool": DeprecatedTool("bash"),
    "playwright_install_tool": DeprecatedTool("bash"),
    "browser_screenshot_tool": DeprecatedTool("bash"),
    "browser_eval_tool": DeprecatedTool("bash"),
    "browser_pdf_tool": DeprecatedTool("bash"),
    "remote_environment_info": DeprecatedTool(
        "version", note=_REMOTE_SESSION_NOTE
    ),
    "remote_run_shell_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_run_python_tool": DeprecatedTool(
        "run_python_code", note=_REMOTE_SESSION_NOTE
    ),
    "remote_shell_start": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_shell_send": DeprecatedTool(
        "send_persistent_shell_input", note=_REMOTE_SESSION_NOTE
    ),
    "remote_shell_read": DeprecatedTool(
        "read_persistent_shell_output", note=_REMOTE_SESSION_NOTE
    ),
    "remote_shell_kill": DeprecatedTool(
        "kill_persistent_shell", note=_REMOTE_SESSION_NOTE
    ),
    "remote_shell_list": DeprecatedTool(
        "list_persistent_shells", note=_REMOTE_SESSION_NOTE
    ),
    "remote_job_start": DeprecatedTool("job", note=_REMOTE_SESSION_NOTE),
    "remote_job_list": DeprecatedTool("job", note=_REMOTE_SESSION_NOTE),
    "remote_job_tail": DeprecatedTool("job", note=_REMOTE_SESSION_NOTE),
    "remote_job_stop": DeprecatedTool("job", note=_REMOTE_SESSION_NOTE),
    "remote_job_retry": DeprecatedTool("job", note=_REMOTE_SESSION_NOTE),
    "remote_list_files": DeprecatedTool(
        "list_files", note=_REMOTE_SESSION_NOTE
    ),
    "remote_tree_view": DeprecatedTool("tree_view", note=_REMOTE_SESSION_NOTE),
    "remote_glob_search": DeprecatedTool(
        "glob_search", note=_REMOTE_SESSION_NOTE
    ),
    "remote_grep_search": DeprecatedTool("search", note=_REMOTE_SESSION_NOTE),
    "remote_read_file": DeprecatedTool("read", note=_REMOTE_SESSION_NOTE),
    "remote_read_many_files": DeprecatedTool("read", note=_REMOTE_SESSION_NOTE),
    "remote_write_file": DeprecatedTool(
        "write_file", note=_REMOTE_SESSION_NOTE
    ),
    "remote_edit_file": DeprecatedTool("edit_lines", note=_REMOTE_SESSION_NOTE),
    "remote_multi_edit_file": DeprecatedTool(
        "hashline_edit", note=_REMOTE_SESSION_NOTE
    ),
    "remote_delete_file_or_dir": DeprecatedTool(
        "delete_file_or_dir", note=_REMOTE_SESSION_NOTE
    ),
    "remote_apply_patch": DeprecatedTool(
        "apply_patch", note=_REMOTE_SESSION_NOTE
    ),
    "remote_copy_file": DeprecatedTool(
        "session_copy", note=_REMOTE_SESSION_NOTE
    ),
    "remote_copy_dir": DeprecatedTool(
        "session_copy", note=_REMOTE_SESSION_NOTE
    ),
    "remote_pull_file": DeprecatedTool(
        "session_copy", note=_REMOTE_SESSION_NOTE
    ),
    "remote_push_file": DeprecatedTool(
        "session_copy", note=_REMOTE_SESSION_NOTE
    ),
    "remote_pull_dir": DeprecatedTool(
        "session_copy", note=_REMOTE_SESSION_NOTE
    ),
    "remote_push_dir": DeprecatedTool(
        "session_copy", note=_REMOTE_SESSION_NOTE
    ),
    "remote_git_clone_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_status_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_diff_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_log_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_checkout_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
    "remote_git_fetch_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_pull_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_add_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_commit_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_push_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_show_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_git_reset_tool": DeprecatedTool("bash", note=_REMOTE_SESSION_NOTE),
    "remote_playwright_install_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
    "remote_browser_screenshot_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
    "remote_browser_get_text_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
    "remote_browser_eval_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
    "remote_browser_pdf_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
    "remote_playwright_run_script_tool": DeprecatedTool(
        "bash", note=_REMOTE_SESSION_NOTE
    ),
}


def deprecated_tool_result(name: str, tool: DeprecatedTool) -> dict[str, Any]:
    """Return a structured diagnostic for one stale client tool call."""

    migration_note = f" {tool.note}" if tool.note else ""
    return {
        "ok": False,
        "message": (
            f"Tool '{name}' was removed in local-shell-mcp {tool.removed_in}. "
            "The client is using an outdated MCP tool snapshot."
        ),
        "data": {
            "status": "stale_tool_snapshot",
            "deprecated_tool": name,
            "replacement": tool.replacement,
            "removed_in": tool.removed_in,
            "help_url": DEPRECATED_TOOL_HELP_URL,
            "assistant_instruction": (
                "Do not retry this deprecated tool. Explain that the MCP client is using "
                "a stale local-shell-mcp tool snapshot and ask the user to refresh the App's "
                "tools, or remove and re-add the App when refresh is unavailable. After the "
                f"snapshot is updated, use '{tool.replacement}'.{migration_note}"
            ),
        },
    }


class DeprecatedToolFastMCP(FastMCP):
    """FastMCP variant that keeps removed names as non-enumerated tombstones."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Return a tombstone diagnostic or dispatch a current tool normally."""
        deprecated = DEPRECATED_TOOLS.get(name)
        if deprecated is not None:
            return deprecated_tool_result(name, deprecated)
        return await super().call_tool(name, arguments)
