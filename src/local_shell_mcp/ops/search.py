"""Search workspace text files and produce compact directory trees for code-navigation tools."""

import asyncio
import fnmatch
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..config.settings import get_settings
from ..schemas.result_models.search import (
    GlobSearchOutput,
    GrepDisplayLine,
    GrepMatch,
    GrepSearchOutput,
    TreeViewOutput,
)
from ..tool_session.store import get_tool_session_store, resolve_session_path
from .files import read_file_execute
from .search_core import (
    LineRanges as _LineRanges,
)
from .search_core import (
    SearchConfig,
    SearchWindowMatch,
    build_rg_argv,
    clamp_search_result_limit,
    display_windows,
    parse_rg_match_record,
)
from .search_core import (
    SearchPaths as _SearchPaths,
)
from .search_core import (
    line_in_ranges as _line_in_ranges,
)
from .search_core import (
    looks_like_glob as _looks_like_glob,
)
from .search_core import (
    merge_line_ranges as _merge_line_ranges,
)
from .search_core import (
    search_match_path as _search_match_path,
)
from .search_core import (
    search_path_items as _search_path_items,
)
from .search_core import (
    split_line_scoped_search_path as _split_line_scoped_search_path,
)
from .utils.path import missing_path_context, relative_display, resolve_path
from .utils.remote_session import call_remote_session_tool


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


_SEARCH_CONTEXT_RADIUS = 1


@dataclass(frozen=True)
class _RawSearchMatch:
    """One returned actual match plus path-scope metadata for display context."""

    match: GrepMatch
    scoped_ranges: _LineRanges | None


def _grep_display_output(
    raw_matches: list[_RawSearchMatch],
    cwd: str,
    session_id: str | None,
    radius: int,
) -> tuple[list[GrepDisplayLine], str]:
    """Return displayed search lines and copyable grouped hashline text."""
    displayed: list[GrepDisplayLine] = []
    sections: list[str] = []
    window_matches = [
        SearchWindowMatch(
            path=raw.match.path,
            line=raw.match.line,
            scoped_ranges=raw.scoped_ranges,
        )
        for raw in raw_matches
    ]
    for window in display_windows(window_matches, cwd, radius):
        try:
            read_result = read_file_execute(
                window.read_path, window.start, window.end, session_id
            )
        except OSError, UnicodeDecodeError, ValueError:
            continue
        seen_range = (
            read_result.seen_ranges[0] if read_result.seen_ranges else None
        )
        if sections:
            sections.append("")
        sections.append(read_result.numbered_content)
        for line in read_result.lines:
            displayed.append(
                GrepDisplayLine(
                    path=read_result.path,
                    line=line.line,
                    kind=(
                        "match"
                        if line.line in window.match_lines
                        else "context"
                    ),
                    text=line.text,
                    numbered_line=f"{line.line}:{line.text}",
                    session_id=read_result.session_id,
                    snapshot_id=read_result.snapshot_id,
                    file_sha256=read_result.file_sha256,
                    seen_range=seen_range,
                )
            )
    return displayed, "\n".join(sections)


def _split_search_scopes(
    cwd: str, paths: _SearchPaths
) -> tuple[list[str], list[str], dict[str, _LineRanges]]:
    """Return ripgrep path args, glob args, and optional per-file line filters."""
    base = resolve_path(cwd, must_exist=True)
    path_args: list[str] = []
    seen_path_args: set[str] = set()
    glob_args: list[str] = []
    line_scopes: dict[str, _LineRanges] = {}
    unrestricted_files: set[str] = set()
    for item in _search_path_items(paths):
        if _looks_like_glob(item):
            glob_args.append(item)
            continue
        path_item, line_ranges = _split_line_scoped_search_path(item)
        raw_path = Path(path_item)
        candidate = raw_path if raw_path.is_absolute() else base / raw_path
        resolved = resolve_path(str(candidate), must_exist=True)
        if line_ranges is not None and not resolved.is_file():
            raise ValueError(
                "search path line selectors are supported only for files"
            )
        if resolved == base:
            path_arg = "."
        elif resolved.is_relative_to(base):
            path_arg = str(resolved.relative_to(base))
        else:
            path_arg = str(resolved)
        if path_arg not in seen_path_args:
            path_args.append(path_arg)
            seen_path_args.add(path_arg)

        resolved_key = str(resolved)
        if line_ranges is None:
            unrestricted_files.add(resolved_key)
            line_scopes.pop(resolved_key, None)
        elif resolved_key not in unrestricted_files:
            line_scopes[resolved_key] = _merge_line_ranges(
                (*line_scopes.get(resolved_key, ()), *line_ranges)
            )
    return path_args, glob_args, line_scopes


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
    """Run ripgrep with workspace path resolution and return structured match records."""
    settings = get_settings()
    config = SearchConfig(
        rg_bin=settings.rg_bin,
        max_results=settings.max_grep_results,
        max_output_bytes=settings.max_output_bytes,
    )
    max_results = clamp_search_result_limit(max_results, config.max_results)
    skip = max(0, skip)
    base = resolve_path(cwd, must_exist=True)
    path_args, glob_args, line_scopes = _split_search_scopes(cwd, paths)
    args = build_rg_argv(
        config,
        query,
        path_args=path_args,
        glob_args=glob_args,
        glob=glob,
        regex=regex,
        case_sensitive=case_sensitive,
        gitignore=gitignore,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return GrepSearchOutput(
            ok=False,
            matches=[],
            displayed_lines=[],
            count=0,
            displayed_count=0,
            context_radius=0,
            skipped=skip,
            truncated=False,
            stderr=f"{config.rg_bin}: {exc}",
            numbered_content="",
        )
    matches: list[GrepMatch] = []
    raw_matches: list[_RawSearchMatch] = []
    matched_seen = 0
    stopped_early = False
    timed_out = False
    stderr_bytes = b""

    async def read_stderr() -> bytes:
        if proc.stderr is None:
            return b""
        return await proc.stderr.read(config.max_output_bytes + 1)

    stderr_task = asyncio.create_task(read_stderr())
    try:
        if proc.stdout is not None:
            while True:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=60
                    )
                except TimeoutError:
                    timed_out = True
                    proc.terminate()
                    break
                if not line:
                    break
                parsed = parse_rg_match_record(line)
                if parsed is None:
                    continue
                path_text = parsed.path
                line_number = parsed.line
                read_path = _search_match_path(cwd, path_text)
                if read_path is not None:
                    try:
                        resolved_match_path = str(
                            resolve_path(read_path, must_exist=True)
                        )
                    except OSError, ValueError:
                        resolved_match_path = None
                else:
                    resolved_match_path = None
                scoped_ranges = (
                    line_scopes.get(resolved_match_path)
                    if resolved_match_path is not None
                    else None
                )
                if scoped_ranges is not None and not _line_in_ranges(
                    line_number, scoped_ranges
                ):
                    continue
                if matched_seen < skip:
                    matched_seen += 1
                    continue
                match = GrepMatch(
                    path=path_text,
                    line=line_number,
                    column=parsed.column,
                    text=parsed.text,
                )
                grounded_match = _ground_match_line(match, cwd, session_id)
                matches.append(grounded_match)
                raw_matches.append(
                    _RawSearchMatch(
                        match=match,
                        scoped_ranges=scoped_ranges,
                    )
                )
                matched_seen += 1
                if len(matches) >= max_results:
                    stopped_early = True
                    proc.terminate()
                    break
        with suppress(TimeoutError):
            await asyncio.wait_for(
                proc.wait(), timeout=2 if stopped_early else 60
            )
    finally:
        if not stderr_task.done():
            stderr_task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            stderr_bytes = await stderr_task
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
            with suppress(Exception, asyncio.CancelledError):
                await proc.wait()

    stderr_truncated = len(stderr_bytes) > config.max_output_bytes
    if stderr_truncated:
        stderr_bytes = stderr_bytes[: config.max_output_bytes]
    displayed_lines, numbered_content = _grep_display_output(
        raw_matches, cwd, session_id, _SEARCH_CONTEXT_RADIUS
    )
    return GrepSearchOutput(
        ok=(not timed_out) and (stopped_early or proc.returncode in {0, 1}),
        matches=matches,
        displayed_lines=displayed_lines,
        count=len(matches),
        displayed_count=len(displayed_lines),
        context_radius=_SEARCH_CONTEXT_RADIUS if matches else 0,
        skipped=skip,
        truncated=stopped_early or stderr_truncated,
        stderr=stderr_bytes.decode(errors="replace"),
        numbered_content=numbered_content,
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
                    "skip": skip,
                    "gitignore": gitignore,
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
        skip=skip,
        gitignore=gitignore,
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
