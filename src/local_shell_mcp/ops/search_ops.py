"""Search workspace text files and produce compact directory trees for code-navigation tools."""

import asyncio
import json
import shlex
from pathlib import Path
from typing import Any, cast

from ..config.settings import get_settings
from ..schemas.result_models.search import (
    GrepMatch,
    GrepSearchOutput,
    TreeViewOutput,
)
from .command_ops import run_shell
from .path_ops import missing_path_context, resolve_path


async def grep_search_execute(
    query: str,
    cwd: str = ".",
    glob: str | None = None,
    regex: bool = True,
    case_sensitive: bool = True,
    max_results: int | None = None,
) -> GrepSearchOutput:
    """Run ripgrep with workspace path resolution and return structured match records."""
    settings = get_settings()
    max_results = max_results or settings.max_grep_results
    args = [settings.rg_bin, "--json", "--line-number", "--column"]
    if not regex:
        args.append("--fixed-strings")
    if not case_sensitive:
        args.append("--ignore-case")
    if glob:
        args.extend(["--glob", glob])
    args.extend(["--", query])
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
        matches.append(
            GrepMatch(
                path=path_text,
                line=match_data.get("line_number"),
                column=first_start + 1
                if isinstance(first_start, int)
                else None,
                text=str(line_text).rstrip("\n"),
            )
        )
        if len(matches) >= max_results:
            break
    return GrepSearchOutput(
        ok=result.exit_code in {0, 1},
        matches=matches,
        count=len(matches),
        truncated=len(matches) >= max_results or result.truncated,
        stderr=result.stderr,
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
