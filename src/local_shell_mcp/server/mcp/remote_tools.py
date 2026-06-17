"""MCP tool registration for remote-worker proxy tools."""

import inspect
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ...remote.transfer import (
    copy_local_dir_to_remote,
    copy_local_file_to_remote,
    copy_remote_dir_to_local,
    copy_remote_dir_to_remote,
    copy_remote_file_to_local,
    copy_remote_file_to_remote,
)
from ...tools.contracts import McpToolContext, ToolResult
from ...tools.responses import (
    handled_error as handled_error_payload,
)
from ...tools.responses import (
    ok_response as ok_response_payload,
)


def _description(text: str) -> str:
    """Return a clean MCP tool description from source text."""
    paragraphs = re.split(r"\n\s*\n", inspect.cleandoc(text))
    return "\n\n".join(
        " ".join(paragraph.split())
        for paragraph in paragraphs
        if paragraph.split()
    )


def ok_response(data: Any = None, message: str = "") -> ToolResult:
    """Return a typed MCP tool result envelope."""
    return ToolResult.model_validate(ok_response_payload(data, message))


def handled_error(exc: Exception) -> ToolResult:
    """Return a typed handled-error MCP tool result envelope."""
    return ToolResult.model_validate(handled_error_payload(exc))


async def _remote_call(
    machine: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> ToolResult:
    """Call a worker-side tool and convert manager failures into tool envelopes."""
    try:
        return ToolResult.model_validate(
            await call_remote_worker_tool(machine, tool, args, timeout_s)
        )
    except Exception as exc:
        return handled_error(exc)


def register_remote_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    oauth_security_meta = context.oauth_security_meta
    settings = context.settings

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Create a one-time command for a remote machine to join this control server. Use when you need to run workspace tools on another worker. Defaults: ttl_s defaults to the configured remote_invite_ttl_s={settings.remote_invite_ttl_s} seconds when omitted. Security: treat the invite as sensitive because it grants enrollment capability."""
        ),
    )
    async def remote_invite(
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
    ) -> ToolResult:
        """Create a one-time remote-worker invite."""
        try:
            return ok_response(await create_remote_invite(name, workdir, ttl_s))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_list_machines() -> ToolResult:
        """List remote worker machines currently known to the control server. Use before running any remote_* tool when you need the machine name or want to verify that a worker is connected."""
        try:
            return ok_response(list_remote_machines())
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_revoke_machine(machine: str) -> ToolResult:
        """Revoke and remove a remote worker machine. Use when a worker should no longer receive jobs or has become stale/untrusted. This is a control-plane action and cannot be undone except by re-inviting the worker."""
        try:
            return ok_response(revoke_remote_machine(machine))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_rename_machine(machine: str, new_name: str) -> ToolResult:
        """Rename a remote worker machine. Use to give a connected worker a clearer stable name before issuing remote jobs. This changes the control-server name used by later remote_* calls."""
        try:
            return ok_response(rename_remote_machine(machine, new_name))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_environment_info(machine: str) -> ToolResult:
        """Return workspace, auth, policy, and basic environment information from a remote worker. Use to verify the remote machine, working directory, runtime versions, and limits before running remote commands or editing remote files."""
        return await _remote_call(machine, "environment_info", {})

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Run one non-interactive shell command on a remote worker. Use for build, test, package-manager, git, and inspection commands that should finish promptly on that worker. Timeout: timeout_s is in seconds and should stay within the run_shell cap of {settings.run_shell_max_timeout_s} seconds on the worker. Output: max_output_bytes caps returned output and the worker default cap is max_output_bytes={settings.max_output_bytes}. For long-running or interactive remote processes, use start_remote_persistent_shell with send_remote_persistent_shell_input and read_remote_persistent_shell_output."""
        ),
    )
    async def run_remote_shell_command(
        machine: str,
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
    ) -> ToolResult:
        """Run one non-interactive shell command on a remote worker."""
        return await _remote_call(
            machine,
            "run_shell_command",
            {
                "command": command,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
            },
            timeout_s,
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Write Python code to a temporary file and execute it on a remote worker. Use for short remote scripts, structured analysis, or file transformations that are easier in Python than shell. Parameters: cwd is resolved on the remote worker and timeout_s defaults to 60 seconds. Timeout: keep timeout_s within the run_shell cap of {settings.run_shell_max_timeout_s} seconds."""
        ),
    )
    async def run_remote_python_code(
        machine: str, code: str, cwd: str = ".", timeout_s: int = 60
    ) -> ToolResult:
        """Write Python code to a temporary file and execute it on a remote worker."""
        return await _remote_call(
            machine,
            "run_python_code",
            {"code": code, "cwd": cwd, "timeout_s": timeout_s},
            timeout_s,
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def start_remote_persistent_shell(
        machine: str,
        cwd: str = ".",
        name: str | None = None,
        command: str | None = None,
    ) -> ToolResult:
        """Start a persistent shell session on a remote worker. Use for remote development servers, watches, REPLs, or interactive commands whose output must be read incrementally. For one-shot commands, use run_remote_shell_command."""
        return await _remote_call(
            machine,
            "start_persistent_shell",
            {"cwd": cwd, "name": name, "command": command},
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def send_remote_persistent_shell_input(
        machine: str, session_id: str, input_text: str, enter: bool = True
    ) -> ToolResult:
        """Send input to a persistent remote shell session. Use after start_remote_persistent_shell when the remote process is waiting for commands or interactive input. enter=false sends partial input without a newline."""
        return await _remote_call(
            machine,
            "send_persistent_shell_input",
            {
                "session_id": session_id,
                "input_text": input_text,
                "enter": enter,
            },
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def read_remote_persistent_shell_output(
        machine: str, session_id: str, lines: int = 200
    ) -> ToolResult:
        """Read recent output from a persistent remote shell session. Use to inspect output from remote long-running or interactive commands. lines bounds the returned recent output."""
        return await _remote_call(
            machine,
            "read_persistent_shell_output",
            {"session_id": session_id, "lines": lines},
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def kill_remote_persistent_shell(
        machine: str, session_id: str
    ) -> ToolResult:
        """Terminate a persistent remote shell session. Use when a remote server, watch, REPL, or stuck command is no longer needed. This affects only the named session on the selected worker."""
        return await _remote_call(
            machine, "kill_persistent_shell", {"session_id": session_id}
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def list_remote_persistent_shells(machine: str) -> ToolResult:
        """List persistent shell sessions on a remote worker. Use before reading, sending to, or killing remote sessions when you need the session_id or active-process overview."""
        return await _remote_call(machine, "list_persistent_shells", {})

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""List files and directories on a remote worker. Use for quick remote directory inspection. Parameters: path is resolved on the remote worker; recursive controls traversal. Result: returns file_info plus limit_count, count, and is_truncated to indicate whether the listing was complete within the limit. Limits: max_entries defaults to 500 and must be between 0 and max_directory_entries={settings.max_directory_entries}."""
        ),
    )
    async def remote_list_files(
        machine: str,
        path: str = ".",
        recursive: bool = False,
        max_entries: int = 500,
    ) -> ToolResult:
        """List files and directories on a remote worker."""
        return await _remote_call(
            machine,
            "list_files",
            {"path": path, "recursive": recursive, "max_entries": max_entries},
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Return a compact directory tree from a remote worker. Use to understand remote project layout before reading or editing files. Parameters: depth defaults to 3. Limits: max_entries defaults to 500 and is capped by max_tree_entries={settings.max_tree_entries}."""
        ),
    )
    async def remote_tree_view(
        machine: str, cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> ToolResult:
        """Return a compact directory tree from a remote worker."""
        return await _remote_call(
            machine,
            "tree_view",
            {"cwd": cwd, "depth": depth, "max_entries": max_entries},
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Find files by glob pattern on a remote worker. Use when you know remote filename patterns and need matching paths. Parameters: cwd narrows the search root. Limits: max_results defaults to 500 and is capped by max_glob_results={settings.max_glob_results}."""
        ),
    )
    async def remote_glob_search(
        machine: str, pattern: str, cwd: str = ".", max_results: int = 500
    ) -> ToolResult:
        """Find files by glob pattern on a remote worker."""
        return await _remote_call(
            machine,
            "glob_search",
            {"pattern": pattern, "cwd": cwd, "max_results": max_results},
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Search remote file contents using ripgrep. Use to locate symbols, usages, or text on a remote worker before reading or editing. Parameters: query is regex by default; glob, cwd, and case_sensitive narrow the search. Limits: max_results is optional and capped by max_grep_results={settings.max_grep_results}."""
        ),
    )
    async def remote_grep_search(
        machine: str,
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
    ) -> ToolResult:
        """Search remote file contents using ripgrep."""
        return await _remote_call(
            machine,
            "grep_search",
            {
                "query": query,
                "cwd": cwd,
                "glob": glob,
                "regex": regex,
                "case_sensitive": case_sensitive,
                "max_results": max_results,
            },
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Read a UTF-8 text file on a remote worker, optionally by line range. Use after locating a remote file to inspect exact content before editing. Parameters: start_line and end_line page large files; binary_preview requests bounded binary preview behavior. Limits: per-file reads are capped by max_file_read_bytes={settings.max_file_read_bytes}."""
        ),
    )
    async def remote_read_file(
        machine: str,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> ToolResult:
        """Read a UTF-8 text file on a remote worker."""
        return await _remote_call(
            machine,
            "read_file",
            {
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "binary_preview": binary_preview,
                "binary_preview_bytes": binary_preview_bytes,
            },
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Read multiple UTF-8 text files on a remote worker with the same optional line range. Use for targeted remote context gathering across known paths. Limits: max_read_many_files={settings.max_read_many_files}, max_read_many_total_bytes={settings.max_read_many_total_bytes}."""
        ),
    )
    async def remote_read_many_files(
        machine: str,
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> ToolResult:
        """Read multiple UTF-8 text files on a remote worker."""
        return await _remote_call(
            machine,
            "read_many_files",
            {
                "paths": paths,
                "start_line": start_line,
                "end_line": end_line,
                "binary_preview": binary_preview,
                "binary_preview_bytes": binary_preview_bytes,
            },
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Write a UTF-8 text file on a remote worker. Use to create or intentionally replace a whole remote file. Parameters: overwrite=false protects existing files. Limits: writes are capped by max_file_write_bytes={settings.max_file_write_bytes}. For precise changes, use remote_edit_file or remote_apply_patch."""
        ),
    )
    async def remote_write_file(
        machine: str, path: str, content: str, overwrite: bool = True
    ) -> ToolResult:
        """Write a UTF-8 text file on a remote worker."""
        return await _remote_call(
            machine,
            "write_file",
            {"path": path, "content": content, "overwrite": overwrite},
        )

    @mcp.tool(
        structured_output=True,
        meta=oauth_security_meta,
        description=_description(
            f"""Replace exact text in a remote file. Use for small precise remote edits after reading the target file. Parameters: old must match exactly; replace_all=true should be used only when every exact occurrence should change. Limits: writes are capped by max_file_write_bytes={settings.max_file_write_bytes}."""
        ),
    )
    async def remote_edit_file(
        machine: str, path: str, old: str, new: str, replace_all: bool = False
    ) -> ToolResult:
        """Replace exact text in a remote file."""
        return await _remote_call(
            machine,
            "edit_file",
            {"path": path, "old": old, "new": new, "replace_all": replace_all},
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_multi_edit_file(
        machine: str, path: str, edits: list[dict]
    ) -> ToolResult:
        """Apply multiple exact-text edits to one remote file. Use when several small remote replacements should be made together. Each edit needs old, new, and optional replace_all; read the file first to avoid stale or ambiguous edits."""
        return await _remote_call(
            machine, "multi_edit_file", {"path": path, "edits": edits}
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_delete_file_or_dir(
        machine: str, path: str, recursive: bool = False
    ) -> ToolResult:
        """Delete a file or directory on a remote worker. Use only when remote removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
        return await _remote_call(
            machine,
            "delete_file_or_dir",
            {"path": path, "recursive": recursive},
        )

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_copy_file(
        src_machine: str,
        src_path: str,
        dst_machine: str,
        dst_path: str,
        overwrite: bool = True,
        chunk_size: int | None = None,
    ) -> ToolResult:
        """Copy one file between two remote worker machines through the control server. Use for binary-safe remote-to-remote transfer. Parameters: src_machine and dst_machine are exact names from remote_list_machines; src_path is the source file on src_machine; dst_path is the destination file path on dst_machine; overwrite controls replacing an existing destination file; chunk_size optionally overrides the transfer chunk size and usually should be omitted."""
        try:
            return ok_response(
                await copy_remote_file_to_remote(
                    src_machine,
                    src_path,
                    dst_machine,
                    dst_path,
                    overwrite,
                    chunk_size,
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_copy_dir(
        src_machine: str,
        src_path: str,
        dst_machine: str,
        dst_path: str,
        overwrite: bool = False,
        chunk_size: int | None = None,
    ) -> ToolResult:
        """Copy a directory tree between two remote worker machines through the control server. Parameters: src_machine and dst_machine are exact names from remote_list_machines; src_path is the source directory; dst_path is the destination directory; overwrite controls replacing an existing destination; chunk_size usually should be omitted."""
        try:
            return ok_response(
                await copy_remote_dir_to_remote(
                    src_machine,
                    src_path,
                    dst_machine,
                    dst_path,
                    overwrite,
                    chunk_size,
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_pull_file(
        machine: str,
        remote_path: str,
        local_path: str,
        overwrite: bool = True,
        chunk_size: int | None = None,
    ) -> ToolResult:
        """Copy one file from a remote worker into the control server workspace. Parameters: machine is the exact remote name from remote_list_machines; remote_path is the source file on that worker; local_path is the local destination file; overwrite controls replacing an existing local file; chunk_size usually should be omitted."""
        try:
            return ok_response(
                await copy_remote_file_to_local(
                    machine, remote_path, local_path, overwrite, chunk_size
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_push_file(
        local_path: str,
        machine: str,
        remote_path: str,
        overwrite: bool = True,
        chunk_size: int | None = None,
    ) -> ToolResult:
        """Copy one file from the control server workspace to a remote worker. Parameters: local_path is the source file in the local workspace; machine is the exact remote name from remote_list_machines; remote_path is the target file on that worker; overwrite controls replacing an existing remote file; chunk_size usually should be omitted."""
        try:
            return ok_response(
                await copy_local_file_to_remote(
                    local_path, machine, remote_path, overwrite, chunk_size
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_pull_dir(
        machine: str,
        remote_path: str,
        local_path: str,
        overwrite: bool = False,
        chunk_size: int | None = None,
    ) -> ToolResult:
        """Copy a directory tree from a remote worker into the control server workspace. Parameters: machine is the exact remote name from remote_list_machines; remote_path is the source directory on that worker; local_path is the local target directory; overwrite controls replacing an existing local target; chunk_size usually should be omitted."""
        try:
            return ok_response(
                await copy_remote_dir_to_local(
                    machine, remote_path, local_path, overwrite, chunk_size
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_push_dir(
        local_path: str,
        machine: str,
        remote_path: str,
        overwrite: bool = False,
        chunk_size: int | None = None,
    ) -> ToolResult:
        """Copy a directory tree from the control server workspace to a remote worker. Parameters: local_path is the source directory in the local workspace; machine is the exact remote name from remote_list_machines; remote_path is the target directory; overwrite controls replacing an existing target; chunk_size usually should be omitted."""
        try:
            return ok_response(
                await copy_local_dir_to_remote(
                    local_path, machine, remote_path, overwrite, chunk_size
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(structured_output=True, meta=oauth_security_meta)
    async def remote_apply_patch(
        machine: str, patch: str, cwd: str = "."
    ) -> ToolResult:
        """Apply a unified diff on a remote worker using git apply. Use for larger remote edits, multi-file changes, additions, and deletions when a patch is clearer than exact replacements. cwd controls where patch paths resolve on the remote worker."""
        return await _remote_call(
            machine, "apply_patch", {"patch": patch, "cwd": cwd}
        )
