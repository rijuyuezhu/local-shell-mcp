"""Remote worker MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ...remote import remote_manager
from ..base import McpToolContext, ToolRegistry
from .common import handled_error, ok_response


class RemoteToolRegistry(ToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_remote_mcp(mcp, context)


def register_remote_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    protected_meta = context.protected_meta

    async def _remote_call(
        machine: str, tool: str, args: dict, timeout_s: int | None = None
    ) -> dict:
        try:
            return await remote_manager().call(machine, tool, args, timeout_s)
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_invite(
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
    ) -> dict:
        """Create a one-time command for a remote machine to join this control server. Use when you need to run workspace tools on another worker. The invite expires after ttl_s seconds and should be treated as sensitive because it grants enrollment capability."""
        try:
            return ok_response(
                await remote_manager().create_invite(name, workdir, ttl_s)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_list_machines() -> dict:
        """List remote worker machines currently known to the control server. Use before running any remote_* tool when you need the machine name or want to verify that a worker is connected."""
        try:
            return ok_response(remote_manager().list_machines())
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_revoke_machine(machine: str) -> dict:
        """Revoke and remove a remote worker machine. Use when a worker should no longer receive jobs or has become stale/untrusted. This is a control-plane action and cannot be undone except by re-inviting the worker."""
        try:
            return ok_response(remote_manager().revoke(machine))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_rename_machine(machine: str, new_name: str) -> dict:
        """Rename a remote worker machine. Use to give a connected worker a clearer stable name before issuing remote jobs. This changes the control-server name used by later remote_* calls."""
        try:
            return ok_response(remote_manager().rename(machine, new_name))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_environment_info(machine: str) -> dict:
        """Return workspace, auth, policy, and basic environment information from a remote worker. Use to verify the remote machine, working directory, runtime versions, and limits before running remote commands or editing remote files."""
        return await _remote_call(machine, "environment_info", {})

    @mcp.tool(meta=protected_meta)
    async def remote_run_shell_tool(
        machine: str,
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
    ) -> dict:
        """Run one non-interactive shell command on a remote worker. Use for build, test, package-manager, git, and inspection commands that should finish promptly on that worker. timeout_s is in seconds and max_output_bytes caps output. For long-running or interactive remote processes, use remote_shell_start with remote_shell_send and remote_shell_read."""
        return await _remote_call(
            machine,
            "run_shell_tool",
            {
                "command": command,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
            },
            timeout_s,
        )

    @mcp.tool(meta=protected_meta)
    async def remote_run_python_tool(
        machine: str, code: str, cwd: str = ".", timeout_s: int = 60
    ) -> dict:
        """Write Python code to a temporary file and execute it on a remote worker. Use for short remote scripts, structured analysis, or file transformations that are easier in Python than shell. cwd is resolved on the remote worker and timeout_s is in seconds."""
        return await _remote_call(
            machine,
            "run_python_tool",
            {"code": code, "cwd": cwd, "timeout_s": timeout_s},
            timeout_s,
        )

    @mcp.tool(meta=protected_meta)
    async def remote_shell_start(
        machine: str,
        cwd: str = ".",
        name: str | None = None,
        command: str | None = None,
    ) -> dict:
        """Start a persistent shell session on a remote worker. Use for remote development servers, watches, REPLs, or interactive commands whose output must be read incrementally. Prefer remote_run_shell_tool for one-shot commands."""
        return await _remote_call(
            machine,
            "shell_start",
            {"cwd": cwd, "name": name, "command": command},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_shell_send(
        machine: str, session_id: str, input_text: str, enter: bool = True
    ) -> dict:
        """Send input to a persistent remote shell session. Use after remote_shell_start when the remote process is waiting for commands or interactive input. enter=false sends partial input without a newline."""
        return await _remote_call(
            machine,
            "shell_send",
            {
                "session_id": session_id,
                "input_text": input_text,
                "enter": enter,
            },
        )

    @mcp.tool(meta=protected_meta)
    async def remote_shell_read(
        machine: str, session_id: str, lines: int = 200
    ) -> dict:
        """Read recent output from a persistent remote shell session. Use to inspect output from remote long-running or interactive commands. lines bounds the returned recent output."""
        return await _remote_call(
            machine, "shell_read", {"session_id": session_id, "lines": lines}
        )

    @mcp.tool(meta=protected_meta)
    async def remote_shell_kill(machine: str, session_id: str) -> dict:
        """Terminate a persistent remote shell session. Use when a remote server, watch, REPL, or stuck command is no longer needed. This affects only the named session on the selected worker."""
        return await _remote_call(
            machine, "shell_kill", {"session_id": session_id}
        )

    @mcp.tool(meta=protected_meta)
    async def remote_shell_list(machine: str) -> dict:
        """List persistent shell sessions on a remote worker. Use before reading, sending to, or killing remote sessions when you need the session_id or active-process overview."""
        return await _remote_call(machine, "shell_list", {})

    @mcp.tool(meta=protected_meta)
    async def remote_list_files(
        machine: str,
        path: str = ".",
        recursive: bool = False,
        max_entries: int = 500,
    ) -> dict:
        """List files and directories on a remote worker. Use for quick remote directory inspection. path is resolved on the remote worker; recursive and max_entries control traversal size."""
        return await _remote_call(
            machine,
            "list_files",
            {"path": path, "recursive": recursive, "max_entries": max_entries},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_tree_view(
        machine: str, cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree from a remote worker. Use to understand remote project layout before reading or editing files. depth and max_entries bound output."""
        return await _remote_call(
            machine,
            "tree_view",
            {"cwd": cwd, "depth": depth, "max_entries": max_entries},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_glob_search(
        machine: str, pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern on a remote worker. Use when you know remote filename patterns and need matching paths. cwd narrows the search root and max_results bounds output."""
        return await _remote_call(
            machine,
            "glob_search",
            {"pattern": pattern, "cwd": cwd, "max_results": max_results},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_grep_search(
        machine: str,
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
    ) -> dict:
        """Search remote file contents using ripgrep. Use to locate symbols, usages, or text on a remote worker before reading or editing. query is regex by default; glob, cwd, case_sensitive, and max_results narrow the search."""
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

    @mcp.tool(meta=protected_meta)
    async def remote_read_file(
        machine: str,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read a UTF-8 text file on a remote worker, optionally by line range. Use after locating a remote file to inspect exact content before editing. start_line and end_line page large files; binary_preview requests bounded binary preview behavior."""
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

    @mcp.tool(meta=protected_meta)
    async def remote_read_many_files(
        machine: str,
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read multiple UTF-8 text files on a remote worker with the same optional line range. Use for targeted remote context gathering across known paths. Server-side limits bound file count and total bytes."""
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

    @mcp.tool(meta=protected_meta)
    async def remote_write_file(
        machine: str, path: str, content: str, overwrite: bool = True
    ) -> dict:
        """Write a UTF-8 text file on a remote worker. Use to create or intentionally replace a whole remote file. overwrite=false protects existing files; for precise changes prefer remote_edit_file or remote_apply_patch."""
        return await _remote_call(
            machine,
            "write_file",
            {"path": path, "content": content, "overwrite": overwrite},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_edit_file(
        machine: str, path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a remote file. Use for small precise remote edits after reading the target file. old must match exactly; replace_all=true should be used only when every exact occurrence should change."""
        return await _remote_call(
            machine,
            "edit_file",
            {"path": path, "old": old, "new": new, "replace_all": replace_all},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_multi_edit_file(
        machine: str, path: str, edits: list[dict]
    ) -> dict:
        """Apply multiple exact-text edits to one remote file. Use when several small remote replacements should be made together. Each edit needs old, new, and optional replace_all; read the file first to avoid stale or ambiguous edits."""
        return await _remote_call(
            machine, "multi_edit_file", {"path": path, "edits": edits}
        )

    @mcp.tool(meta=protected_meta)
    async def remote_delete_file_or_dir(
        machine: str, path: str, recursive: bool = False
    ) -> dict:
        """Delete a file or directory on a remote worker. Use only when remote removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
        return await _remote_call(
            machine,
            "delete_file_or_dir",
            {"path": path, "recursive": recursive},
        )

    @mcp.tool(meta=protected_meta)
    async def remote_apply_patch(
        machine: str, patch: str, cwd: str = "."
    ) -> dict:
        """Apply a unified diff on a remote worker using git apply. Use for larger remote edits, multi-file changes, additions, and deletions when a patch is clearer than exact replacements. cwd controls where patch paths resolve on the remote worker."""
        return await _remote_call(
            machine, "apply_patch", {"patch": patch, "cwd": cwd}
        )
