"""Remote worker MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ...remote.tool_specs import REMOTE_WORKER_TOOL_SPECS
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from ..responses import handled_error, ok_response


async def _remote_invite(args: dict[str, Any]) -> dict[str, Any]:
    return await create_remote_invite(
        args.get("name"), args.get("workdir"), args.get("ttl_s")
    )


async def _remote_list_machines(args: dict[str, Any]) -> dict[str, Any]:
    return list_remote_machines()


async def _remote_revoke_machine(args: dict[str, Any]) -> dict[str, Any]:
    return revoke_remote_machine(args["machine"])


async def _remote_rename_machine(args: dict[str, Any]) -> dict[str, Any]:
    return rename_remote_machine(args["machine"], args["new_name"])


def _remote_worker_args(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key != "machine"}


async def _remote_worker_tool(
    args: dict[str, Any], tool_name: str, timeout_s: int | None = None
) -> dict[str, Any]:
    result = await call_remote_worker_tool(
        args["machine"], tool_name, _remote_worker_args(args), timeout_s
    )
    if result.get("ok", False):
        data = result.get("data")
        return data if isinstance(data, dict) else {"result": data}
    return result


def _make_remote_worker_handler(
    tool_name: str,
    *,
    timeout_arg: str | None = None,
    default_timeout: int | None = None,
) -> ToolHandler:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        timeout_s = (
            args.get(timeout_arg, default_timeout)
            if timeout_arg is not None
            else None
        )
        return await _remote_worker_tool(args, tool_name, timeout_s)

    return handler


async def _remote_call(
    machine: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call a worker-side tool and convert manager failures into tool envelopes."""
    try:
        return await call_remote_worker_tool(machine, tool, args, timeout_s)
    except Exception as exc:
        return handled_error(exc)


REMOTE_CONTROL_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/remote_invite", "remote_invite"),
    HttpToolRoute("GET", "/tools/remote_list_machines", "remote_list_machines"),
    HttpToolRoute(
        "POST", "/tools/remote_revoke_machine", "remote_revoke_machine"
    ),
    HttpToolRoute(
        "POST", "/tools/remote_rename_machine", "remote_rename_machine"
    ),
)

REMOTE_HTTP_ROUTES = REMOTE_CONTROL_HTTP_ROUTES + tuple(
    HttpToolRoute("POST", spec.http_path, spec.public_name)
    for spec in REMOTE_WORKER_TOOL_SPECS
)

REMOTE_CONTROL_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "remote_invite": _remote_invite,
    "remote_list_machines": _remote_list_machines,
    "remote_revoke_machine": _remote_revoke_machine,
    "remote_rename_machine": _remote_rename_machine,
}

REMOTE_HTTP_HANDLERS: dict[str, ToolHandler] = {
    **REMOTE_CONTROL_HTTP_HANDLERS,
    **{
        spec.public_name: _make_remote_worker_handler(
            spec.worker_tool,
            timeout_arg=spec.timeout_arg,
            default_timeout=spec.default_timeout,
        )
        for spec in REMOTE_WORKER_TOOL_SPECS
    },
}


class RemoteToolRegistry(StaticHttpToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"

    routes = REMOTE_HTTP_ROUTES
    handlers = REMOTE_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_remote_mcp(mcp, context)


def register_remote_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    protected_meta = context.protected_meta
    settings = context.settings

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Create a one-time command for a remote machine to join this control server. "
            "Use when you need to run workspace tools on another worker. "
            f"ttl_s defaults to the configured remote_invite_ttl_s={settings.remote_invite_ttl_s} seconds when omitted. "
            "The invite should be treated as sensitive because it grants enrollment capability."
        ),
    )
    async def remote_invite(
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
    ) -> dict:
        """Create a one-time remote-worker invite."""
        try:
            return ok_response(await create_remote_invite(name, workdir, ttl_s))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_list_machines() -> dict:
        """List remote worker machines currently known to the control server. Use before running any remote_* tool when you need the machine name or want to verify that a worker is connected."""
        try:
            return ok_response(list_remote_machines())
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_revoke_machine(machine: str) -> dict:
        """Revoke and remove a remote worker machine. Use when a worker should no longer receive jobs or has become stale/untrusted. This is a control-plane action and cannot be undone except by re-inviting the worker."""
        try:
            return ok_response(revoke_remote_machine(machine))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_rename_machine(machine: str, new_name: str) -> dict:
        """Rename a remote worker machine. Use to give a connected worker a clearer stable name before issuing remote jobs. This changes the control-server name used by later remote_* calls."""
        try:
            return ok_response(rename_remote_machine(machine, new_name))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def remote_environment_info(machine: str) -> dict:
        """Return workspace, auth, policy, and basic environment information from a remote worker. Use to verify the remote machine, working directory, runtime versions, and limits before running remote commands or editing remote files."""
        return await _remote_call(machine, "environment_info", {})

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Run one non-interactive shell command on a remote worker. Use for build, test, package-manager, git, and inspection commands that should finish promptly on that worker. "
            f"timeout_s is in seconds and should stay within the public run_shell cap of {settings.public_run_shell_max_timeout_s} seconds on the worker; "
            f"max_output_bytes caps returned output and the worker default cap is max_output_bytes={settings.max_output_bytes}. "
            "For long-running or interactive remote processes, use remote_shell_start with remote_shell_send and remote_shell_read."
        ),
    )
    async def remote_run_shell_tool(
        machine: str,
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
    ) -> dict:
        """Run one non-interactive shell command on a remote worker."""
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

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Write Python code to a temporary file and execute it on a remote worker. "
            "Use for short remote scripts, structured analysis, or file transformations that are easier in Python than shell. "
            f"cwd is resolved on the remote worker and timeout_s defaults to 60 seconds; keep it within the public run_shell cap of {settings.public_run_shell_max_timeout_s} seconds."
        ),
    )
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

    @mcp.tool(
        meta=protected_meta,
        description=(
            "List files and directories on a remote worker. Use for quick remote directory inspection. "
            f"path is resolved on the remote worker; recursive controls traversal; max_entries defaults to 500 and is capped by max_directory_entries={settings.max_directory_entries}."
        ),
    )
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

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Return a compact directory tree from a remote worker. Use to understand remote project layout before reading or editing files. "
            f"depth defaults to 3; max_entries defaults to 500 and is capped by max_tree_entries={settings.max_tree_entries}."
        ),
    )
    async def remote_tree_view(
        machine: str, cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree from a remote worker."""
        return await _remote_call(
            machine,
            "tree_view",
            {"cwd": cwd, "depth": depth, "max_entries": max_entries},
        )

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Find files by glob pattern on a remote worker. Use when you know remote filename patterns and need matching paths. "
            f"cwd narrows the search root; max_results defaults to 500 and is capped by max_glob_results={settings.max_glob_results}."
        ),
    )
    async def remote_glob_search(
        machine: str, pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern on a remote worker."""
        return await _remote_call(
            machine,
            "glob_search",
            {"pattern": pattern, "cwd": cwd, "max_results": max_results},
        )

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Search remote file contents using ripgrep. Use to locate symbols, usages, or text on a remote worker before reading or editing. "
            f"query is regex by default; glob, cwd, and case_sensitive narrow the search; max_results is optional and capped by max_grep_results={settings.max_grep_results}."
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

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Read a UTF-8 text file on a remote worker, optionally by line range. Use after locating a remote file to inspect exact content before editing. "
            f"start_line and end_line page large files; binary_preview requests bounded binary preview behavior; per-file reads are capped by max_file_read_bytes={settings.max_file_read_bytes}."
        ),
    )
    async def remote_read_file(
        machine: str,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
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
        meta=protected_meta,
        description=(
            "Read multiple UTF-8 text files on a remote worker with the same optional line range. Use for targeted remote context gathering across known paths. "
            f"Server-side limits bound file count and total bytes: max_read_many_files={settings.max_read_many_files}, max_read_many_total_bytes={settings.max_read_many_total_bytes}."
        ),
    )
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

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Write a UTF-8 text file on a remote worker. Use to create or intentionally replace a whole remote file. "
            f"Writes are capped by max_file_write_bytes={settings.max_file_write_bytes}; overwrite=false protects existing files; for precise changes prefer remote_edit_file or remote_apply_patch."
        ),
    )
    async def remote_write_file(
        machine: str, path: str, content: str, overwrite: bool = True
    ) -> dict:
        """Write a UTF-8 text file on a remote worker."""
        return await _remote_call(
            machine,
            "write_file",
            {"path": path, "content": content, "overwrite": overwrite},
        )

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Replace exact text in a remote file. Use for small precise remote edits after reading the target file. "
            f"old must match exactly; replace_all=true should be used only when every exact occurrence should change. Writes are capped by max_file_write_bytes={settings.max_file_write_bytes}."
        ),
    )
    async def remote_edit_file(
        machine: str, path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a remote file."""
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
