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
    oauth_meta = context.oauth_meta

    async def _remote_call(
        machine: str, tool: str, args: dict, timeout_s: int | None = None
    ) -> dict:
        try:
            return await remote_manager().call(machine, tool, args, timeout_s)
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def remote_invite(
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
    ) -> dict:
        """Create a one-time command for a remote machine to join this control server."""
        try:
            return ok_response(
                await remote_manager().create_invite(name, workdir, ttl_s)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def remote_list_machines() -> dict:
        """List remote worker machines connected to this control server."""
        try:
            return ok_response(remote_manager().list_machines())
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def remote_revoke_machine(machine: str) -> dict:
        """Revoke and remove a remote worker machine."""
        try:
            return ok_response(remote_manager().revoke(machine))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def remote_rename_machine(machine: str, new_name: str) -> dict:
        """Rename a remote worker machine."""
        try:
            return ok_response(remote_manager().rename(machine, new_name))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def remote_environment_info(machine: str) -> dict:
        """Return remote workspace, auth, policy, and basic environment information."""
        return await _remote_call(machine, "environment_info", {})

    @mcp.tool(meta=oauth_meta)
    async def remote_run_shell_tool(
        machine: str,
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
    ) -> dict:
        """Run a shell command on a remote worker machine."""
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

    @mcp.tool(meta=oauth_meta)
    async def remote_run_python_tool(
        machine: str, code: str, cwd: str = ".", timeout_s: int = 60
    ) -> dict:
        """Write Python code to a temporary file and execute it on a remote worker."""
        return await _remote_call(
            machine,
            "run_python_tool",
            {"code": code, "cwd": cwd, "timeout_s": timeout_s},
            timeout_s,
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_shell_start(
        machine: str,
        cwd: str = ".",
        name: str | None = None,
        command: str | None = None,
    ) -> dict:
        """Start a persistent shell session on a remote worker."""
        return await _remote_call(
            machine,
            "shell_start",
            {"cwd": cwd, "name": name, "command": command},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_shell_send(
        machine: str, session_id: str, input_text: str, enter: bool = True
    ) -> dict:
        """Send input to a persistent remote shell session."""
        return await _remote_call(
            machine,
            "shell_send",
            {
                "session_id": session_id,
                "input_text": input_text,
                "enter": enter,
            },
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_shell_read(
        machine: str, session_id: str, lines: int = 200
    ) -> dict:
        """Read recent output from a persistent remote shell session."""
        return await _remote_call(
            machine, "shell_read", {"session_id": session_id, "lines": lines}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_shell_kill(machine: str, session_id: str) -> dict:
        """Kill a persistent remote shell session."""
        return await _remote_call(
            machine, "shell_kill", {"session_id": session_id}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_shell_list(machine: str) -> dict:
        """List persistent shell sessions on a remote worker."""
        return await _remote_call(machine, "shell_list", {})

    @mcp.tool(meta=oauth_meta)
    async def remote_list_files(
        machine: str,
        path: str = ".",
        recursive: bool = False,
        max_entries: int = 500,
    ) -> dict:
        """List files and directories on a remote worker."""
        return await _remote_call(
            machine,
            "list_files",
            {"path": path, "recursive": recursive, "max_entries": max_entries},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_tree_view(
        machine: str, cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree from a remote worker."""
        return await _remote_call(
            machine,
            "tree_view",
            {"cwd": cwd, "depth": depth, "max_entries": max_entries},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_glob_search(
        machine: str, pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern on a remote worker."""
        return await _remote_call(
            machine,
            "glob_search",
            {"pattern": pattern, "cwd": cwd, "max_results": max_results},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_grep_search(
        machine: str,
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
    ) -> dict:
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

    @mcp.tool(meta=oauth_meta)
    async def remote_read_file(
        machine: str,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read a UTF-8 text file on a remote worker, optionally by line range."""
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

    @mcp.tool(meta=oauth_meta)
    async def remote_read_many_files(
        machine: str,
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
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

    @mcp.tool(meta=oauth_meta)
    async def remote_write_file(
        machine: str, path: str, content: str, overwrite: bool = True
    ) -> dict:
        """Write a UTF-8 text file on a remote worker."""
        return await _remote_call(
            machine,
            "write_file",
            {"path": path, "content": content, "overwrite": overwrite},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_edit_file(
        machine: str, path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a remote file."""
        return await _remote_call(
            machine,
            "edit_file",
            {"path": path, "old": old, "new": new, "replace_all": replace_all},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_multi_edit_file(
        machine: str, path: str, edits: list[dict]
    ) -> dict:
        """Apply multiple exact-text edits to one remote file."""
        return await _remote_call(
            machine, "multi_edit_file", {"path": path, "edits": edits}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_delete_file_or_dir(
        machine: str, path: str, recursive: bool = False
    ) -> dict:
        """Delete a file or directory on a remote worker."""
        return await _remote_call(
            machine,
            "delete_file_or_dir",
            {"path": path, "recursive": recursive},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_apply_patch(
        machine: str, patch: str, cwd: str = "."
    ) -> dict:
        """Apply a unified diff on a remote worker using git apply."""
        return await _remote_call(
            machine, "apply_patch", {"patch": patch, "cwd": cwd}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_clone_tool(
        machine: str,
        repo_url: str,
        dest: str | None = None,
        branch: str | None = None,
        cwd: str = ".",
    ) -> dict:
        """Clone a Git repository on a remote worker."""
        return await _remote_call(
            machine,
            "git_clone_tool",
            {"repo_url": repo_url, "dest": dest, "branch": branch, "cwd": cwd},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_status_tool(machine: str, cwd: str = ".") -> dict:
        """Run git status on a remote worker."""
        return await _remote_call(machine, "git_status_tool", {"cwd": cwd})

    @mcp.tool(meta=oauth_meta)
    async def remote_git_diff_tool(
        machine: str,
        cwd: str = ".",
        staged: bool = False,
        path: str | None = None,
        stat: bool = False,
    ) -> dict:
        """Run git diff on a remote worker."""
        return await _remote_call(
            machine,
            "git_diff_tool",
            {"cwd": cwd, "staged": staged, "path": path, "stat": stat},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_log_tool(
        machine: str, cwd: str = ".", max_count: int = 20
    ) -> dict:
        """Show recent git commits on a remote worker."""
        return await _remote_call(
            machine, "git_log_tool", {"cwd": cwd, "max_count": max_count}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_checkout_tool(
        machine: str, cwd: str, ref: str, create: bool = False
    ) -> dict:
        """Checkout an existing ref or create a branch on a remote worker."""
        return await _remote_call(
            machine,
            "git_checkout_tool",
            {"cwd": cwd, "ref": ref, "create": create},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_fetch_tool(
        machine: str, cwd: str = ".", remote: str = "origin", prune: bool = True
    ) -> dict:
        """Fetch a git remote on a remote worker."""
        return await _remote_call(
            machine,
            "git_fetch_tool",
            {"cwd": cwd, "remote": remote, "prune": prune},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_pull_tool(
        machine: str, cwd: str = ".", ff_only: bool = True
    ) -> dict:
        """Pull current branch on a remote worker."""
        return await _remote_call(
            machine, "git_pull_tool", {"cwd": cwd, "ff_only": ff_only}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_add_tool(
        machine: str, cwd: str = ".", paths: list[str] | None = None
    ) -> dict:
        """Stage paths on a remote worker."""
        return await _remote_call(
            machine, "git_add_tool", {"cwd": cwd, "paths": paths}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_commit_tool(
        machine: str, cwd: str, message: str, all_changes: bool = False
    ) -> dict:
        """Create a git commit on a remote worker."""
        return await _remote_call(
            machine,
            "git_commit_tool",
            {"cwd": cwd, "message": message, "all_changes": all_changes},
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_push_tool(
        machine: str,
        cwd: str,
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = True,
    ) -> dict:
        """Push current HEAD from a remote worker."""
        return await _remote_call(
            machine,
            "git_push_tool",
            {
                "cwd": cwd,
                "remote": remote,
                "branch": branch,
                "set_upstream": set_upstream,
            },
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_show_tool(
        machine: str, cwd: str = ".", ref: str = "HEAD", path: str | None = None
    ) -> dict:
        """Show a commit, object, or file at ref:path on a remote worker."""
        return await _remote_call(
            machine, "git_show_tool", {"cwd": cwd, "ref": ref, "path": path}
        )

    @mcp.tool(meta=oauth_meta)
    async def remote_git_reset_tool(
        machine: str, cwd: str = ".", mode: str = "soft", ref: str = "HEAD"
    ) -> dict:
        """Run git reset on a remote worker. Modes: soft, mixed, hard."""
        return await _remote_call(
            machine, "git_reset_tool", {"cwd": cwd, "mode": mode, "ref": ref}
        )
