"""Declarative remote-worker tool proxy specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteWorkerToolSpec:
    """Describe one remote worker tool and its optional public REST proxy."""

    public_name: str
    """Public proxy tool name exposed by the control server."""
    worker_tool: str
    """Underlying tool name executed on the remote worker."""
    http_path: str | None
    """Public REST path for the proxy, or None for worker-internal tools."""
    timeout_arg: str | None = None
    """Optional argument name that should receive the proxy timeout."""
    default_timeout: int | None = None
    """Default timeout passed through when the caller omits one."""

    @property
    def expose_http(self) -> bool:
        """Return whether this worker tool has a public REST proxy."""
        return bool(self.public_name and self.http_path)


REMOTE_WORKER_TOOL_SPECS: tuple[RemoteWorkerToolSpec, ...] = (
    RemoteWorkerToolSpec("", "send_persistent_shell_input", None),
    RemoteWorkerToolSpec("", "read_persistent_shell_output", None),
    RemoteWorkerToolSpec("", "kill_persistent_shell", None),
    RemoteWorkerToolSpec("", "list_persistent_shells", None),
    RemoteWorkerToolSpec(
        "", "run_python_code", None, timeout_arg="timeout_s", default_timeout=60
    ),
    RemoteWorkerToolSpec("", "session_start", None),
    RemoteWorkerToolSpec("", "list_files", None),
    RemoteWorkerToolSpec("", "tree_view", None),
    RemoteWorkerToolSpec("", "glob_search", None),
    RemoteWorkerToolSpec("", "write_file", None),
    RemoteWorkerToolSpec("", "delete_file_or_dir", None),
    RemoteWorkerToolSpec("", "secret_scan", None),
    RemoteWorkerToolSpec("", "read", None),
    RemoteWorkerToolSpec("", "search", None),
    RemoteWorkerToolSpec("", "edit_lines", None),
    RemoteWorkerToolSpec("", "bash", None),
    RemoteWorkerToolSpec("", "job", None),
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
