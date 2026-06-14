"""Declarative remote-worker tool proxy specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteWorkerToolSpec:
    """Describe one remote worker tool and its optional public REST proxy."""

    public_name: str
    worker_tool: str
    http_path: str | None
    timeout_arg: str | None = None
    default_timeout: int | None = None

    @property
    def expose_http(self) -> bool:
        """Return whether this worker tool has a public REST proxy."""
        return bool(self.public_name and self.http_path)


REMOTE_WORKER_TOOL_SPECS: tuple[RemoteWorkerToolSpec, ...] = (
    RemoteWorkerToolSpec(
        "remote_environment_info",
        "environment_info",
        "/tools/remote_environment_info",
    ),
    RemoteWorkerToolSpec(
        "run_remote_shell_command",
        "run_shell_command",
        "/tools/run_remote_shell_command",
        timeout_arg="timeout_s",
    ),
    RemoteWorkerToolSpec(
        "run_remote_python_code",
        "run_python_code",
        "/tools/run_remote_python_code",
        timeout_arg="timeout_s",
        default_timeout=60,
    ),
    RemoteWorkerToolSpec(
        "start_remote_persistent_shell",
        "start_persistent_shell",
        "/tools/start_remote_persistent_shell",
    ),
    RemoteWorkerToolSpec(
        "send_remote_persistent_shell_input",
        "send_persistent_shell_input",
        "/tools/send_remote_persistent_shell_input",
    ),
    RemoteWorkerToolSpec(
        "read_remote_persistent_shell_output",
        "read_persistent_shell_output",
        "/tools/read_remote_persistent_shell_output",
    ),
    RemoteWorkerToolSpec(
        "kill_remote_persistent_shell",
        "kill_persistent_shell",
        "/tools/kill_remote_persistent_shell",
    ),
    RemoteWorkerToolSpec(
        "list_remote_persistent_shells",
        "list_persistent_shells",
        "/tools/list_remote_persistent_shells",
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
    RemoteWorkerToolSpec("", "transfer_stat", None),
    RemoteWorkerToolSpec("", "transfer_read_chunk", None),
    RemoteWorkerToolSpec("", "transfer_begin_write", None),
    RemoteWorkerToolSpec("", "transfer_write_chunk", None),
    RemoteWorkerToolSpec("", "transfer_finish_write", None),
    RemoteWorkerToolSpec("", "transfer_abort_write", None),
    RemoteWorkerToolSpec("", "transfer_alloc_temp_path", None),
    RemoteWorkerToolSpec("", "transfer_pack_dir", None),
    RemoteWorkerToolSpec("", "transfer_unpack_archive", None),
)

REMOTE_WORKER_TOOL_NAMES = frozenset(
    spec.worker_tool for spec in REMOTE_WORKER_TOOL_SPECS
)
