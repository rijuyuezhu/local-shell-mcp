"""Declarative remote-worker tool proxy specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteWorkerToolSpec:
    """Describe one public remote_* proxy for a worker-side local tool."""

    public_name: str
    worker_tool: str
    http_path: str
    timeout_arg: str | None = None
    default_timeout: int | None = None


REMOTE_WORKER_TOOL_SPECS: tuple[RemoteWorkerToolSpec, ...] = (
    RemoteWorkerToolSpec(
        "remote_environment_info",
        "environment_info",
        "/tools/remote_environment_info",
    ),
    RemoteWorkerToolSpec(
        "remote_run_shell_tool",
        "run_shell_tool",
        "/tools/remote_run_shell",
        timeout_arg="timeout_s",
    ),
    RemoteWorkerToolSpec(
        "remote_run_python_tool",
        "run_python_tool",
        "/tools/remote_run_python",
        timeout_arg="timeout_s",
        default_timeout=60,
    ),
    RemoteWorkerToolSpec(
        "remote_shell_start", "shell_start", "/tools/remote_shell_start"
    ),
    RemoteWorkerToolSpec(
        "remote_shell_send", "shell_send", "/tools/remote_shell_send"
    ),
    RemoteWorkerToolSpec(
        "remote_shell_read", "shell_read", "/tools/remote_shell_read"
    ),
    RemoteWorkerToolSpec(
        "remote_shell_kill", "shell_kill", "/tools/remote_shell_kill"
    ),
    RemoteWorkerToolSpec(
        "remote_shell_list", "shell_list", "/tools/remote_shell_list"
    ),
    RemoteWorkerToolSpec(
        "remote_list_files", "list_files", "/tools/remote_list_files"
    ),
    RemoteWorkerToolSpec("remote_tree_view", "tree_view", "/tools/remote_tree"),
    RemoteWorkerToolSpec(
        "remote_glob_search", "glob_search", "/tools/remote_glob"
    ),
    RemoteWorkerToolSpec(
        "remote_grep_search", "grep_search", "/tools/remote_grep"
    ),
    RemoteWorkerToolSpec(
        "remote_read_file", "read_file", "/tools/remote_read_file"
    ),
    RemoteWorkerToolSpec(
        "remote_read_many_files",
        "read_many_files",
        "/tools/remote_read_many_files",
    ),
    RemoteWorkerToolSpec(
        "remote_write_file", "write_file", "/tools/remote_write_file"
    ),
    RemoteWorkerToolSpec(
        "remote_edit_file", "edit_file", "/tools/remote_edit_file"
    ),
    RemoteWorkerToolSpec(
        "remote_multi_edit_file",
        "multi_edit_file",
        "/tools/remote_multi_edit_file",
    ),
    RemoteWorkerToolSpec(
        "remote_delete_file_or_dir",
        "delete_file_or_dir",
        "/tools/remote_delete",
    ),
    RemoteWorkerToolSpec(
        "remote_apply_patch", "apply_patch", "/tools/remote_apply_patch"
    ),
)

REMOTE_WORKER_TOOL_NAMES = frozenset(
    spec.worker_tool for spec in REMOTE_WORKER_TOOL_SPECS
)
