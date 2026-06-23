"""Search workspace text files and produce compact directory trees for code-navigation tools."""

import asyncio
import fnmatch
import json
import shlex
from pathlib import Path
from typing import Any, cast

from ..config.settings import get_settings
from ..schemas.result_models.search import (
    GlobSearchOutput,
    GrepMatch,
    GrepSearchOutput,
    TreeViewOutput,
)
from ..tool_session.store import get_tool_session_store
from .files import read_file_execute
from .shell import run_shell
from .utils.path import missing_path_context, relative_display, resolve_path
from .utils.remote_session import call_remote_session_tool


def glob_search_execute(
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


def _search_match_path(cwd: str, path_text: str | None) -> str | None:
    """Return a workspace-readable path for a ripgrep match path."""
    if path_text is None:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return str(path)
    return str(Path(cwd) / path)


def _ground_match_line(
    match: GrepMatch, cwd: str, session_id: str | None
) -> GrepMatch:
    """Attach read-style grounding metadata to one grep match line."""
    read_path = _search_match_path(cwd, match.path)
    if read_path is None or match.line is None:
        return match
    try:
        read_result = read_file_execute(
            read_path, match.line, match.line, session_id
        )
    except OSError, UnicodeDecodeError, ValueError:
        return match
    seen_range = read_result.seen_ranges[0] if read_result.seen_ranges else None
    return match.model_copy(
        update={
            "path": read_result.path,
            "numbered_line": read_result.numbered_content,
            "session_id": read_result.session_id,
            "snapshot_id": read_result.snapshot_id,
            "file_sha256": read_result.file_sha256,
            "seen_range": seen_range,
        }
    )


def _grep_numbered_content(matches: list[GrepMatch]) -> str:
    """Return grouped line-numbered snippets for grep matches."""
    lines: list[str] = []
    current_path: str | None = None
    for match in matches:
        if match.path != current_path:
            if lines:
                lines.append("")
            current_path = match.path
            lines.append(str(match.path or "<unknown>"))
        lines.append(match.numbered_line or f"{match.line}|{match.text}")
    return "\n".join(lines)


type _SearchPaths = str | list[str] | None


def _search_path_items(paths: _SearchPaths) -> list[str]:
    """Normalize optional high-level search path scopes."""
    if paths is None:
        return []
    if isinstance(paths, str):
        return [paths] if paths else []
    return [path for path in paths if path]


def _looks_like_glob(path: str) -> bool:
    """Return whether a search path should be treated as a glob scope."""
    return any(char in path for char in "*?[")


def _split_search_scopes(
    cwd: str, paths: _SearchPaths
) -> tuple[list[str], list[str]]:
    """Return ripgrep path args and glob args for high-level search scopes."""
    base = resolve_path(cwd, must_exist=True)
    path_args: list[str] = []
    glob_args: list[str] = []
    for item in _search_path_items(paths):
        if _looks_like_glob(item):
            glob_args.append(item)
            continue
        raw_path = Path(item)
        candidate = raw_path if raw_path.is_absolute() else base / raw_path
        resolved = resolve_path(str(candidate), must_exist=True)
        if resolved == base:
            path_args.append(".")
        elif resolved.is_relative_to(base):
            path_args.append(str(resolved.relative_to(base)))
        else:
            path_args.append(str(resolved))
    return path_args, glob_args


async def grep_search_execute(
    query: str,
    cwd: str = ".",
    glob: str | None = None,
    regex: bool = True,
    case_sensitive: bool = True,
    max_results: int | None = None,
    session_id: str | None = None,
    paths: _SearchPaths = None,
) -> GrepSearchOutput:
    """Run ripgrep with workspace path resolution and return structured match records."""
    settings = get_settings()
    max_results = max_results or settings.max_grep_results
    args = [settings.rg_bin, "--json", "--line-number", "--column"]
    if not regex:
        args.append("--fixed-strings")
    if not case_sensitive:
        args.append("--ignore-case")
    path_args, glob_args = _split_search_scopes(cwd, paths)
    for glob_arg in glob_args:
        args.extend(["--glob", glob_arg])
    if glob:
        args.extend(["--glob", glob])
    args.extend(["--", query, *path_args])
    cmd = " ".join(shlex.quote(x) for x in args)
    result = await run_shell(
        cmd, cwd=cwd, timeout_s=60, max_output_bytes=1_000_000
    )
    matches: list[GrepMatch] = []
    for line in result.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        record = cast(dict[str, Any], obj)
        if record.get("type") != "match":
            continue
        data = record.get("data", {})
        if not isinstance(data, dict):
            continue
        match_data = cast(dict[str, Any], data)
        raw_submatches = match_data.get("submatches")
        submatches: list[Any] = (
            cast(list[Any], raw_submatches)
            if isinstance(raw_submatches, list)
            else []
        )
        first: dict[str, Any] = {}
        if submatches and isinstance(submatches[0], dict):
            first = cast(dict[str, Any], submatches[0])
        first_start = first.get("start")
        raw_path_data = match_data.get("path")
        raw_line_data = match_data.get("lines")
        path_data = (
            cast(dict[str, Any], raw_path_data)
            if isinstance(raw_path_data, dict)
            else {}
        )
        line_data = (
            cast(dict[str, Any], raw_line_data)
            if isinstance(raw_line_data, dict)
            else {}
        )
        path_text = path_data.get("text")
        line_text = line_data.get("text", "")
        match = GrepMatch(
            path=path_text,
            line=match_data.get("line_number"),
            column=first_start + 1 if isinstance(first_start, int) else None,
            text=str(line_text).rstrip("\n"),
        )
        matches.append(_ground_match_line(match, cwd, session_id))
        if len(matches) >= max_results:
            break
    return GrepSearchOutput(
        ok=result.exit_code in {0, 1},
        matches=matches,
        count=len(matches),
        truncated=len(matches) >= max_results or result.truncated,
        stderr=result.stderr,
        numbered_content=_grep_numbered_content(matches),
    )


async def search_execute(
    pattern: str,
    paths: _SearchPaths = None,
    cwd: str = ".",
    regex: bool = True,
    case_sensitive: bool = True,
    max_results: int | None = None,
    session_id: str | None = None,
) -> GrepSearchOutput:
    """Search code content with optional path scopes and edit grounding."""
    if session_id is not None:
        session = get_tool_session_store().touch_session(session_id)
        if session.target == "remote":
            data = await call_remote_session_tool(
                session,
                "search",
                {
                    "pattern": pattern,
                    "paths": paths,
                    "regex": regex,
                    "case_sensitive": case_sensitive,
                    "max_results": max_results,
                },
            )
            return GrepSearchOutput.model_validate(data)
        if cwd == ".":
            cwd = session.workdir
    return await grep_search_execute(
        pattern,
        cwd=cwd,
        regex=regex,
        case_sensitive=case_sensitive,
        max_results=max_results,
        session_id=session_id,
        paths=paths,
    )


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
    cwd: str = ".", depth: int = 3, max_entries: int = 500
) -> TreeViewOutput:
    """Expose tree generation through an async API used by MCP and HTTP handlers."""
    return await asyncio.to_thread(tree_view_sync, cwd, depth, max_entries)
