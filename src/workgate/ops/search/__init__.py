"""Search workspace text files and produce compact directory trees for code-navigation tools."""

import asyncio
import fnmatch
from pathlib import Path

from ...config.settings import Settings, get_settings
from ...schemas.result_models.search import (
    GlobSearchOutput,
    GrepSearchOutput,
    TreeViewOutput,
)
from ...tool_session.bindings import LocalSessionBinding
from ...tool_session.resolver import SessionResolver
from ...tool_session.store import (
    ToolSessionStore,
    get_tool_session_store,
    resolve_session_path,
)
from ..utils.path import missing_path_context, relative_display, resolve_path
from ..utils.remote_session import call_remote_session_tool
from .composition import build_local_search_runner, build_search_service
from .core import SearchPaths as _SearchPaths
from .service import RemoteSearchClient, SearchRequest


def _glob_search_local(
    pattern: str, cwd: str = ".", max_results: int = 500
) -> GlobSearchOutput:
    """Find workspace paths matching a glob pattern without exceeding the configured result limit."""
    settings = get_settings()
    base = resolve_path(cwd, must_exist=True)
    results: list[str] = []
    limit = max(1, min(max_results, settings.max_glob_results))
    for item in base.rglob("*"):
        rel = str(item.relative_to(base))
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(item.name, pattern):
            results.append(relative_display(item))
            if len(results) >= limit:
                break
    return GlobSearchOutput(paths=results)


async def glob_search_execute(
    session_id: str, pattern: str, cwd: str = ".", max_results: int = 500
) -> GlobSearchOutput:
    """Find paths matching a glob pattern inside an explicit agent/workspace session."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "glob_search",
            {
                "pattern": pattern,
                "cwd": cwd,
                "max_results": max_results,
            },
        )
        return GlobSearchOutput.model_validate(data)
    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    return await asyncio.to_thread(
        _glob_search_local, pattern, str(resolved_cwd), max_results
    )


def _legacy_search_dependencies() -> tuple[Settings, ToolSessionStore]:
    """Acquire ambient dependencies only for compatibility Search facades."""
    return get_settings(), get_tool_session_store()


async def grep_search_execute(
    query: str,
    cwd: str = ".",
    glob: str | None = None,
    regex: bool = True,
    case_sensitive: bool = True,
    max_results: int | None = None,
    session_id: str | None = None,
    paths: _SearchPaths = None,
    skip: int = 0,
    gitignore: bool = True,
) -> GrepSearchOutput:
    """Run the legacy local grep facade through the explicit Search runner."""
    settings, store = _legacy_search_dependencies()
    binding: LocalSessionBinding | None = None
    if session_id is not None:
        resolved = SessionResolver(store).resolve_active_binding(session_id)
        if not isinstance(resolved, LocalSessionBinding):
            raise ValueError("grep_search_execute only supports local sessions")
        binding = resolved
    runner = build_local_search_runner(settings, store)
    return await runner.search(
        SearchRequest(
            pattern=query,
            paths=paths,
            regex=regex,
            case_sensitive=case_sensitive,
            max_results=max_results,
            skip=skip,
            gitignore=gitignore,
            glob=glob,
        ),
        workdir=cwd,
        binding=binding,
    )


async def search_execute(
    pattern: str,
    paths: _SearchPaths = None,
    cwd: str = ".",
    regex: bool = True,
    case_sensitive: bool = True,
    max_results: int | None = None,
    session_id: str | None = None,
    skip: int = 0,
    gitignore: bool = True,
) -> GrepSearchOutput:
    """Search code content while preserving the legacy public facade signature."""
    settings, store = _legacy_search_dependencies()
    request = SearchRequest(
        pattern=pattern,
        paths=paths,
        regex=regex,
        case_sensitive=case_sensitive,
        max_results=max_results,
        skip=skip,
        gitignore=gitignore,
    )
    if session_id is None:
        return await build_local_search_runner(settings, store).search(
            request,
            workdir=cwd,
        )

    if cwd == ".":
        service = build_search_service(
            settings,
            store,
            remote=RemoteSearchClient(),
        )
        return await service.search(
            session_id,
            pattern,
            paths,
            regex,
            case_sensitive,
            max_results,
            skip,
            gitignore,
        )

    binding = SessionResolver(store).resolve_active_binding(session_id)
    if isinstance(binding, LocalSessionBinding):
        return await build_local_search_runner(settings, store).search(
            request,
            workdir=cwd,
            binding=binding,
        )
    return await RemoteSearchClient().search(binding, request)


def tree_view_sync(
    cwd: str = ".", depth: int = 3, max_entries: int = 500
) -> TreeViewOutput:
    """Build a compact, depth-limited directory tree while skipping common generated directories."""
    settings = get_settings()
    base = resolve_path(cwd)
    if not base.exists():
        context = missing_path_context(base, max_entries=min(max_entries, 100))
        return TreeViewOutput(
            root=context["path"],
            exists=False,
            is_directory=False,
            entries=[],
            count=0,
            truncated=False,
            message=f"Path does not exist: {context['path']}",
            nearest_existing_parent=context["nearest_existing_parent"],
            nearest_parent_entries=context["nearest_parent_entries"],
            nearest_parent_entries_truncated=context["truncated"],
        )
    if not base.is_dir():
        return TreeViewOutput(
            root=str(base),
            exists=True,
            is_directory=False,
            entries=[],
            count=0,
            truncated=False,
            message=f"Path exists but is not a directory: {base}",
        )

    depth = max(0, min(depth, 10))
    limit = max(1, min(max_entries, settings.max_tree_entries))
    rows: list[str] = []
    count = 0
    truncated = False

    def walk(directory: Path, current_depth: int) -> None:
        nonlocal count, truncated
        if current_depth >= depth or count >= limit:
            return
        try:
            iterator = directory.iterdir()
        except OSError:
            return
        for path in iterator:
            if path.name == ".git":
                continue
            if count >= limit:
                truncated = True
                return
            rel = path.relative_to(base)
            indent = "  " * (len(rel.parts) - 1)
            suffix = "/" if path.is_dir() else ""
            rows.append(f"{indent}{path.name}{suffix}")
            count += 1
            if path.is_dir():
                walk(path, current_depth + 1)
            if count >= limit:
                truncated = True
                return

    walk(base, 0)
    return TreeViewOutput(
        root=str(base),
        exists=True,
        is_directory=True,
        entries=rows,
        count=count,
        truncated=truncated,
    )


async def tree_view_execute(
    session_id: str, cwd: str = ".", depth: int = 3, max_entries: int = 500
) -> TreeViewOutput:
    """Expose session-bound tree generation through an async API used by MCP and HTTP handlers."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "tree_view",
            {
                "cwd": cwd,
                "depth": depth,
                "max_entries": max_entries,
            },
        )
        return TreeViewOutput.model_validate(data)
    resolved_cwd = resolve_session_path(session, cwd)
    return await asyncio.to_thread(
        tree_view_sync, str(resolved_cwd), depth, max_entries
    )
