"""Git MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.git_ops import (
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
from ..base import HttpToolRoute, McpToolContext, ToolHandler, ToolRegistry
from .common import handled_error, ok_response


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


GIT_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/git/status", "git_status_tool"),
    HttpToolRoute("POST", "/tools/git/diff", "git_diff_tool"),
    HttpToolRoute("POST", "/tools/git/log", "git_log_tool"),
    HttpToolRoute("POST", "/tools/git/clone", "git_clone_tool"),
    HttpToolRoute("POST", "/tools/git/checkout", "git_checkout_tool"),
    HttpToolRoute("POST", "/tools/git/fetch", "git_fetch_tool"),
    HttpToolRoute("POST", "/tools/git/pull", "git_pull_tool"),
    HttpToolRoute("POST", "/tools/git/add", "git_add_tool"),
    HttpToolRoute("POST", "/tools/git/commit", "git_commit_tool"),
    HttpToolRoute("POST", "/tools/git/push", "git_push_tool"),
    HttpToolRoute("POST", "/tools/git/show", "git_show_tool"),
    HttpToolRoute("POST", "/tools/git/reset", "git_reset_tool"),
)

GIT_HTTP_HANDLERS: dict[str, ToolHandler] = {
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
}


class GitToolRegistry(ToolRegistry):
    """Register git operation tools."""

    name = "git"

    def http_routes(self):
        return GIT_HTTP_ROUTES

    def http_handlers(self):
        return GIT_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_git_mcp(mcp, context)


def register_git_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    oauth_meta = context.oauth_meta

    @mcp.tool(meta=oauth_meta)
    async def git_clone_tool(
        repo_url: str,
        dest: str | None = None,
        branch: str | None = None,
        cwd: str = ".",
    ) -> dict:
        """Clone a Git repository."""
        try:
            return ok_response(await git_clone(repo_url, dest, branch, cwd))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_status_tool(cwd: str = ".") -> dict:
        """Run git status and list remotes."""
        try:
            return ok_response(await git_status(cwd))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_diff_tool(
        cwd: str = ".",
        staged: bool = False,
        path: str | None = None,
        stat: bool = False,
    ) -> dict:
        """Run git diff."""
        try:
            return ok_response(await git_diff(cwd, staged, path, stat))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_log_tool(cwd: str = ".", max_count: int = 20) -> dict:
        """Show recent git commits."""
        try:
            return ok_response(await git_log(cwd, max_count))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_checkout_tool(
        cwd: str, ref: str, create: bool = False
    ) -> dict:
        """Checkout an existing ref or create a branch."""
        try:
            return ok_response(await git_checkout(cwd, ref, create))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_fetch_tool(
        cwd: str = ".", remote: str = "origin", prune: bool = True
    ) -> dict:
        """Fetch a git remote."""
        try:
            return ok_response(await git_fetch(cwd, remote, prune))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_pull_tool(cwd: str = ".", ff_only: bool = True) -> dict:
        """Pull current branch."""
        try:
            return ok_response(await git_pull(cwd, ff_only))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_add_tool(
        cwd: str = ".", paths: list[str] | None = None
    ) -> dict:
        """Stage paths for commit."""
        try:
            return ok_response(await git_add(cwd, paths))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_commit_tool(
        cwd: str, message: str, all_changes: bool = False
    ) -> dict:
        """Create a git commit."""
        try:
            return ok_response(await git_commit(cwd, message, all_changes))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_push_tool(
        cwd: str,
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = True,
    ) -> dict:
        """Push current HEAD to a remote branch."""
        try:
            return ok_response(
                await git_push(cwd, remote, branch, set_upstream)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_show_tool(
        cwd: str = ".", ref: str = "HEAD", path: str | None = None
    ) -> dict:
        """Show a commit, object, or file at ref:path."""
        try:
            return ok_response(await git_show(cwd, ref, path))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_reset_tool(
        cwd: str = ".", mode: str = "soft", ref: str = "HEAD"
    ) -> dict:
        """Run git reset. Modes: soft, mixed, hard."""
        try:
            return ok_response(await git_reset(cwd, mode, ref))
        except Exception as exc:
            return handled_error(exc)
