"""Shared local tool invocation helpers used by HTTP adapters and MCP wrappers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..ops.fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    multi_edit_text,
    read_text,
    write_text,
)
from ..ops.git_ops import (
    git_add,
    git_checkout,
    git_clone,
    git_commit,
    git_diff,
    git_fetch,
    git_log,
    git_pull,
    git_push,
    git_reset,
    git_show,
    git_status,
)
from ..ops.search_ops import grep, tree
from ..ops.shell_ops import (
    kill_shell,
    list_shells,
    public_run_shell,
    read_shell,
    send_shell,
    start_shell,
)
from ..ops.todo_ops import todo_read, todo_write
from .registry.common import (
    apply_patch_text,
    read_audit_tail_entries,
    read_many_files_sync,
    run_python_script,
    run_secret_scan,
    to_thread,
)

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


async def _run_shell_tool(args: dict[str, Any]) -> dict[str, Any]:
    return (
        await public_run_shell(
            args["command"],
            args.get("cwd", "."),
            args.get("timeout_s"),
            args.get("max_output_bytes"),
        )
    ).model_dump()


async def run_python_script_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await run_python_script(
        args["code"], args.get("cwd", "."), args.get("timeout_s", 60)
    )


async def _shell_start(args: dict[str, Any]) -> dict[str, Any]:
    return await start_shell(
        args.get("cwd", "."), args.get("name"), args.get("command")
    )


async def _shell_send(args: dict[str, Any]) -> dict[str, Any]:
    return await send_shell(
        args["session_id"], args["input_text"], args.get("enter", True)
    )


async def _shell_read(args: dict[str, Any]) -> dict[str, Any]:
    return await read_shell(args["session_id"], args.get("lines", 200))


async def _shell_kill(args: dict[str, Any]) -> dict[str, Any]:
    return await kill_shell(args["session_id"])


async def _shell_list(args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    return await list_shells()


async def _list_files(args: dict[str, Any]) -> list[dict[str, Any]]:
    return await to_thread(
        list_dir,
        args.get("path", "."),
        args.get("recursive", False),
        args.get("max_entries", 500),
    )


async def _tree_view(args: dict[str, Any]) -> dict[str, Any]:
    return await tree(
        args.get("cwd", "."),
        args.get("depth", 3),
        args.get("max_entries", 500),
    )


async def _glob_search(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "paths": await to_thread(
            glob_paths,
            args["pattern"],
            args.get("cwd", "."),
            args.get("max_results", 500),
        )
    }


async def _grep_search(args: dict[str, Any]) -> dict[str, Any]:
    return await grep(
        args["query"],
        args.get("cwd", "."),
        args.get("glob"),
        args.get("regex", True),
        args.get("case_sensitive", True),
        args.get("max_results"),
    )


async def _read_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        read_text,
        args["path"],
        args.get("start_line"),
        args.get("end_line"),
        args.get("binary_preview"),
        args.get("binary_preview_bytes", 256),
    )


async def _read_many_files(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        read_many_files_sync,
        args["paths"],
        args.get("start_line"),
        args.get("end_line"),
        args.get("binary_preview"),
        args.get("binary_preview_bytes", 256),
    )


async def _write_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        write_text, args["path"], args["content"], args.get("overwrite", True)
    )


async def _edit_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        edit_text,
        args["path"],
        args["old"],
        args["new"],
        args.get("replace_all", False),
    )


async def _multi_edit_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(multi_edit_text, args["path"], args["edits"])


async def _delete_file_or_dir(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        delete_path, args["path"], args.get("recursive", False)
    )


async def _apply_patch(args: dict[str, Any]) -> dict[str, Any]:
    return await apply_patch_text(args["patch"], args.get("cwd", "."))


async def _git_clone_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_clone(
        args["repo_url"],
        args.get("dest"),
        args.get("branch"),
        args.get("cwd", "."),
    )


async def _git_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_status(args.get("cwd", "."))


async def _git_diff_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_diff(
        args.get("cwd", "."),
        args.get("staged", False),
        args.get("path"),
        args.get("stat", False),
    )


async def _git_log_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_log(args.get("cwd", "."), args.get("max_count", 20))


async def _git_checkout_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_checkout(
        args["cwd"], args["ref"], args.get("create", False)
    )


async def _git_fetch_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_fetch(
        args.get("cwd", "."),
        args.get("remote", "origin"),
        args.get("prune", True),
    )


async def _git_pull_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_pull(args.get("cwd", "."), args.get("ff_only", True))


async def _git_add_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_add(args.get("cwd", "."), args.get("paths"))


async def _git_commit_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_commit(
        args["cwd"], args["message"], args.get("all_changes", False)
    )


async def _git_push_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_push(
        args["cwd"],
        args.get("remote", "origin"),
        args.get("branch"),
        args.get("set_upstream", True),
    )


async def _git_show_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_show(
        args.get("cwd", "."), args.get("ref", "HEAD"), args.get("path")
    )


async def _git_reset_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await git_reset(
        args.get("cwd", "."),
        args.get("mode", "soft"),
        args.get("ref", "HEAD"),
    )


async def secret_scan_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await run_secret_scan(
        args.get("cwd", "."), args.get("glob"), args.get("max_results", 200)
    )


async def _todo_read_tool(args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    return await to_thread(todo_read)


async def _todo_write_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(todo_write, args.get("todos", []))


async def _audit_tail(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(read_audit_tail_entries, args.get("lines", 100))


LOCAL_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "run_shell_tool": _run_shell_tool,
    "run_python_tool": run_python_script_tool,
    "shell_start": _shell_start,
    "shell_send": _shell_send,
    "shell_read": _shell_read,
    "shell_kill": _shell_kill,
    "shell_list": _shell_list,
    "list_files": _list_files,
    "tree_view": _tree_view,
    "glob_search": _glob_search,
    "grep_search": _grep_search,
    "read_file": _read_file,
    "read_many_files": _read_many_files,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "multi_edit_file": _multi_edit_file,
    "delete_file_or_dir": _delete_file_or_dir,
    "apply_patch": _apply_patch,
    "git_clone_tool": _git_clone_tool,
    "git_status_tool": _git_status_tool,
    "git_diff_tool": _git_diff_tool,
    "git_log_tool": _git_log_tool,
    "git_checkout_tool": _git_checkout_tool,
    "git_fetch_tool": _git_fetch_tool,
    "git_pull_tool": _git_pull_tool,
    "git_add_tool": _git_add_tool,
    "git_commit_tool": _git_commit_tool,
    "git_push_tool": _git_push_tool,
    "git_show_tool": _git_show_tool,
    "git_reset_tool": _git_reset_tool,
    "secret_scan": secret_scan_tool,
    "todo_read_tool": _todo_read_tool,
    "todo_write_tool": _todo_write_tool,
    "audit_tail": _audit_tail,
}

HTTP_TOOL_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/tools/run_shell"): "run_shell_tool",
    ("POST", "/tools/shell_start"): "shell_start",
    ("POST", "/tools/shell_send"): "shell_send",
    ("POST", "/tools/shell_read"): "shell_read",
    ("POST", "/tools/shell_kill"): "shell_kill",
    ("GET", "/tools/shell_list"): "shell_list",
    ("POST", "/tools/list_files"): "list_files",
    ("POST", "/tools/tree"): "tree_view",
    ("POST", "/tools/glob"): "glob_search",
    ("POST", "/tools/grep"): "grep_search",
    ("POST", "/tools/read_file"): "read_file",
    ("POST", "/tools/write_file"): "write_file",
    ("POST", "/tools/edit_file"): "edit_file",
    ("POST", "/tools/multi_edit_file"): "multi_edit_file",
    ("POST", "/tools/delete"): "delete_file_or_dir",
    ("POST", "/tools/git/status"): "git_status_tool",
    ("POST", "/tools/git/diff"): "git_diff_tool",
    ("POST", "/tools/git/log"): "git_log_tool",
    ("POST", "/tools/git/clone"): "git_clone_tool",
    ("POST", "/tools/git/checkout"): "git_checkout_tool",
    ("POST", "/tools/git/fetch"): "git_fetch_tool",
    ("POST", "/tools/git/pull"): "git_pull_tool",
    ("POST", "/tools/git/add"): "git_add_tool",
    ("POST", "/tools/git/commit"): "git_commit_tool",
    ("POST", "/tools/git/push"): "git_push_tool",
    ("POST", "/tools/git/show"): "git_show_tool",
    ("POST", "/tools/git/reset"): "git_reset_tool",
    ("GET", "/tools/todo"): "todo_read_tool",
    ("POST", "/tools/todo"): "todo_write_tool",
}


async def call_local_tool(
    tool_name: str, args: dict[str, Any] | None = None
) -> Any:
    """Invoke a local tool by canonical MCP tool name."""
    try:
        handler = LOCAL_TOOL_HANDLERS[tool_name]
    except KeyError as exc:
        raise KeyError(f"Unknown local tool: {tool_name}") from exc
    return await handler(args or {})
