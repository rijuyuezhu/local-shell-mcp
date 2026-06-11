"""Git MCP tool registry."""

from __future__ import annotations

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
from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .common import _handled_error, _ok


class GitToolRegistry(ToolRegistry):
    """Register git operation tools."""

    name = "git"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {
            "git_clone_tool",
            "git_status_tool",
            "git_diff_tool",
            "git_log_tool",
            "git_checkout_tool",
            "git_fetch_tool",
            "git_pull_tool",
            "git_add_tool",
            "git_commit_tool",
            "git_push_tool",
            "git_show_tool",
            "git_reset_tool",
        }
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

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
            return _ok(await git_clone(repo_url, dest, branch, cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_status_tool(cwd: str = ".") -> dict:
        """Run git status and list remotes."""
        try:
            return _ok(await git_status(cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_diff_tool(
        cwd: str = ".",
        staged: bool = False,
        path: str | None = None,
        stat: bool = False,
    ) -> dict:
        """Run git diff."""
        try:
            return _ok(await git_diff(cwd, staged, path, stat))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_log_tool(cwd: str = ".", max_count: int = 20) -> dict:
        """Show recent git commits."""
        try:
            return _ok(await git_log(cwd, max_count))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_checkout_tool(
        cwd: str, ref: str, create: bool = False
    ) -> dict:
        """Checkout an existing ref or create a branch."""
        try:
            return _ok(await git_checkout(cwd, ref, create))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_fetch_tool(
        cwd: str = ".", remote: str = "origin", prune: bool = True
    ) -> dict:
        """Fetch a git remote."""
        try:
            return _ok(await git_fetch(cwd, remote, prune))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_pull_tool(cwd: str = ".", ff_only: bool = True) -> dict:
        """Pull current branch."""
        try:
            return _ok(await git_pull(cwd, ff_only))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_add_tool(
        cwd: str = ".", paths: list[str] | None = None
    ) -> dict:
        """Stage paths for commit."""
        try:
            return _ok(await git_add(cwd, paths))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_commit_tool(
        cwd: str, message: str, all_changes: bool = False
    ) -> dict:
        """Create a git commit."""
        try:
            return _ok(await git_commit(cwd, message, all_changes))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_push_tool(
        cwd: str,
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = True,
    ) -> dict:
        """Push current HEAD to a remote branch."""
        try:
            return _ok(await git_push(cwd, remote, branch, set_upstream))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_show_tool(
        cwd: str = ".", ref: str = "HEAD", path: str | None = None
    ) -> dict:
        """Show a commit, object, or file at ref:path."""
        try:
            return _ok(await git_show(cwd, ref, path))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_reset_tool(
        cwd: str = ".", mode: str = "soft", ref: str = "HEAD"
    ) -> dict:
        """Run git reset. Modes: soft, mixed, hard."""
        try:
            return _ok(await git_reset(cwd, mode, ref))
        except Exception as exc:
            return _handled_error(exc)
