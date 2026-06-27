"""Provide workspace-aware UTF-8 file operations with path containment and bounded output."""

import codecs
import difflib
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config.settings import get_settings
from ..schemas.input_models.files import ReadFileRequest
from ..schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditFileOutput,
    EditLinesOutput,
    EntryInfo,
    HashlineEditHunkOutput,
    HashlineEditOutput,
    LineRange,
    ListFilesOutput,
    MultiEditFileOutput,
    ReadFileOutput,
    ReadLine,
    ReadManyFilesOutput,
    WriteFileOutput,
)
from ..tool_session.store import (
    file_sha256,
    get_tool_session_store,
    resolve_session_path,
)
from .utils.path import relative_display, resolve_path, workspace_root
from .utils.remote_session import call_remote_session_tool


def list_files_execute(
    path: str = ".",
    recursive: bool = False,
    max_entries: int = 500,
    session_id: str | None = None,
) -> ListFilesOutput:
    """List directory entries up to a limit and report whether results were truncated."""
    settings = get_settings()
    session = (
        get_tool_session_store().touch_session(session_id)
        if session_id is not None
        else None
    )
    base = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    filelist: list[EntryInfo] = []
    max_directory_entries = settings.max_directory_entries
    if not (0 <= max_entries <= max_directory_entries):
        raise ValueError(
            f"max_entries must be between 0 and {max_directory_entries}"
        )
    limit = min(max_entries, max_directory_entries)
    iterator = base.rglob("*") if recursive else base.iterdir()

    truncated = False
    for item in iterator:
        if len(filelist) >= limit:
            truncated = True
            break
        try:
            stat = item.stat()
        except OSError:
            continue
        entry_type = (
            "dir" if item.is_dir() else "file" if item.is_file() else "other"
        )
        filelist.append(
            EntryInfo(
                path=relative_display(item),
                type=entry_type,
                size=stat.st_size if item.is_file() else None,
                modified=stat.st_mtime,
            )
        )
    return ListFilesOutput(
        limit_count=limit,
        count=len(filelist),
        is_truncated=truncated,
        entries=filelist,
    )


async def list_files_dispatch_execute(
    path: str = ".",
    recursive: bool = False,
    max_entries: int = 500,
    session_id: str | None = None,
) -> ListFilesOutput:
    """Dispatch list_files to a local or remote session."""
    if session_id is None:
        return list_files_execute(path, recursive, max_entries, session_id)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "list_files",
            {
                "path": path,
                "recursive": recursive,
                "max_entries": max_entries,
            },
        )
        return ListFilesOutput.model_validate(data)
    return list_files_execute(path, recursive, max_entries, session_id)


type _ReadLineRange = tuple[int | None, int | None]


def _selected_read_lines(
    lines: list[str],
    start_line: int | None,
    end_line: int | None,
) -> list[ReadLine]:
    """Return decoded lines with original line numbers for a requested range."""
    total_lines = len(lines)
    if total_lines == 0:
        return []
    start = max(1, start_line or 1)
    end = min(total_lines, end_line or total_lines)
    if end < start:
        return []
    return [
        ReadLine(line=line_number, text=lines[line_number - 1])
        for line_number in range(start, end + 1)
    ]


def _selected_read_lines_by_ranges(
    lines: list[str], ranges: Sequence[_ReadLineRange]
) -> tuple[list[ReadLine], tuple[tuple[int, int], ...]]:
    """Return decoded lines plus the exact non-empty ranges actually shown."""
    selected_lines: list[ReadLine] = []
    seen_ranges: list[tuple[int, int]] = []
    for start_line, end_line in ranges:
        range_lines = _selected_read_lines(lines, start_line, end_line)
        if not range_lines:
            continue
        selected_lines.extend(range_lines)
        seen_ranges.append((range_lines[0].line, range_lines[-1].line))
    return selected_lines, tuple(seen_ranges)


def _numbered_content(
    lines: list[ReadLine],
    path: str | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Format lines in hashline-style grounded model-facing form."""
    body = "\n".join(f"{line.line}:{line.text}" for line in lines)
    if path is not None and snapshot_id is not None:
        header = "[" + path + "#" + snapshot_id + "]"
        return header + "\n" + body if body else header
    return body


def read_file_execute(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    session_id: str | None = None,
    line_ranges: Sequence[_ReadLineRange] | None = None,
) -> ReadFileOutput:
    """Read a UTF-8 text file by optional line range and record grounding when session-bound."""
    settings = get_settings()
    store = get_tool_session_store()
    session = (
        store.touch_session(session_id) if session_id is not None else None
    )
    p = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    size = p.stat().st_size
    with p.open("rb") as fh:
        data = fh.read(settings.max_file_read_bytes + 1)

    truncated = False
    if len(data) > settings.max_file_read_bytes:
        data = data[: settings.max_file_read_bytes]
        truncated = True
    truncated_bytes = max(0, size - len(data))
    decoder = codecs.getincrementaldecoder("utf-8")()
    text = decoder.decode(data, final=not truncated)
    all_lines = text.splitlines()
    total_lines = len(all_lines)
    range_specs = (
        tuple(line_ranges)
        if line_ranges is not None
        else ((start_line, end_line),)
    )
    selected_lines, seen_ranges = _selected_read_lines_by_ranges(
        all_lines, range_specs
    )
    if (
        line_ranges is not None
        or start_line is not None
        or end_line is not None
    ):
        text = "\n".join(line.text for line in selected_lines)

    start = selected_lines[0].line if selected_lines else None
    end = selected_lines[-1].line if selected_lines else None
    seen_range_models = [
        LineRange(start=range_start, end=range_end)
        for range_start, range_end in seen_ranges
    ]
    relative_path = relative_display(p)
    record = (
        store.record_file_snapshot(
            session_id=session.session_id,
            path=relative_path,
            file_sha256=file_sha256(p),
            total_lines=total_lines,
            seen_ranges=seen_ranges,
        )
        if session is not None
        else None
    )
    return ReadFileOutput(
        path=relative_path,
        bytes=size,
        bytes_read=len(data),
        truncated_bytes=truncated_bytes,
        total_lines=total_lines,
        start_line=start,
        end_line=end,
        line_count=len(selected_lines),
        lines=selected_lines,
        numbered_content=_numbered_content(
            selected_lines,
            relative_path,
            record.snapshot_id if record is not None else None,
        ),
        session_id=record.session_id if record is not None else None,
        snapshot_id=record.snapshot_id if record is not None else None,
        file_sha256=record.file_sha256 if record is not None else None,
        seen_ranges=seen_range_models if record is not None else [],
        truncated=truncated,
        content=text,
    )


type _ReadManyFileSpec = (
    ReadFileRequest
    | tuple[str]
    | tuple[str, int | None]
    | tuple[str, int | None, int | None]
)


def _read_many_file_parts(
    item: _ReadManyFileSpec,
) -> tuple[str, int | None, int | None]:
    """Normalize one read_many_files item into path and optional line range."""
    if isinstance(item, ReadFileRequest):
        return (
            item.path,
            item.start_line,
            item.end_line,
        )
    return (
        item[0],
        item[1] if len(item) > 1 else None,
        item[2] if len(item) > 2 else None,
    )


def read_many_files_execute(
    files_to_read: Sequence[_ReadManyFileSpec],
    session_id: str | None = None,
) -> ReadManyFilesOutput:
    """Read many files with per-file optional line ranges."""
    settings = get_settings()
    if len(files_to_read) > settings.max_read_many_files:
        raise ValueError(
            f"Refusing to read {len(files_to_read)} files; max is {settings.max_read_many_files}"
        )

    files: list[ReadFileOutput] = []
    total_content_bytes = 0
    for item_to_read in files_to_read:
        path, start_line, end_line = _read_many_file_parts(item_to_read)
        item = read_file_execute(path, start_line, end_line, session_id)
        content = item.content
        total_content_bytes += len(content.encode("utf-8"))
        if total_content_bytes > settings.max_read_many_total_bytes:
            raise ValueError(
                f"Refusing to return {total_content_bytes} bytes from read_many_files; "
                f"max is {settings.max_read_many_total_bytes}"
            )
        files.append(item)
    return ReadManyFilesOutput(
        files=files, total_content_bytes=total_content_bytes
    )


def write_file_execute(
    path: str,
    content: str,
    overwrite: bool = True,
    session_id: str | None = None,
) -> WriteFileOutput:
    """Write a text file after path validation, parent creation, and overwrite checks."""
    settings = get_settings()
    data = content.encode("utf-8")
    if len(data) > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {len(data)} bytes; max is {settings.max_file_write_bytes}"
        )
    session = (
        get_tool_session_store().touch_session(session_id)
        if session_id is not None
        else None
    )
    p = (
        resolve_session_path(session, path)
        if session is not None
        else resolve_path(path)
    )
    if p.exists() and not overwrite:
        raise FileExistsError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    created = not p.exists()
    p.write_text(content, encoding="utf-8")
    return WriteFileOutput(
        path=relative_display(p), bytes=len(data), created=created
    )


async def write_file_dispatch_execute(
    path: str,
    content: str,
    overwrite: bool = True,
    session_id: str | None = None,
) -> WriteFileOutput:
    """Dispatch write_file to a local or remote session."""
    if session_id is None:
        return write_file_execute(path, content, overwrite, session_id)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "write_file",
            {
                "path": path,
                "content": content,
                "overwrite": overwrite,
            },
        )
        return WriteFileOutput.model_validate(data)
    return write_file_execute(path, content, overwrite, session_id)


def _newline_for_text(text: str) -> str:
    """Return the dominant newline sequence for whole-line edits."""
    return "\r\n" if "\r\n" in text else "\n"


def _replacement_lines(
    replacement: str,
    *,
    newline: str,
    selected_had_trailing_newline: bool,
    has_following_lines: bool,
) -> list[str]:
    """Return replacement text as whole-line chunks with stable newlines."""
    if replacement == "":
        return []
    text = replacement
    if not text.endswith(("\n", "\r")) and (
        selected_had_trailing_newline or has_following_lines
    ):
        text = f"{text}{newline}"
    return text.splitlines(keepends=True)


def _range_is_visible(
    start_line: int, end_line: int, ranges: tuple[tuple[int, int], ...]
) -> bool:
    """Return whether an edit range is contained in displayed ranges."""
    return any(
        start_line >= visible_start and end_line <= visible_end
        for visible_start, visible_end in ranges
    )


_HASHLINE_HEADER_RE = re.compile(r"^\[(?P<path>.+)#(?P<snapshot>[^\]]+)\]$")
_HASHLINE_ROW_RE = re.compile(r"^(?P<line>\d+):(?P<text>.*)$")
_HASHLINE_SWAP_RE = re.compile(
    r"^SWAP\s+(?P<start>\d+)(?:-(?P<end>\d+))?:\s*$", re.IGNORECASE
)
_HASHLINE_INSERT_RE = re.compile(
    r"^INSERT(?:\s+(?P<where>BEFORE|AFTER))?\s+(?P<line>\d+):\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ParsedHashlineEdit:
    """Parsed hashline replacement or deletion operation."""

    path: str
    snapshot_id: str
    start_line: int
    end_line: int
    replacement: str
    expected_lines: tuple[ReadLine, ...] = ()


@dataclass(frozen=True)
class _ParsedHashlineInsert:
    """Parsed hashline insertion anchored on a visible line."""

    path: str
    snapshot_id: str
    anchor_line: int
    insert_after: bool
    inserted_lines: tuple[str, ...]


type _ParsedHashlineOperation = _ParsedHashlineEdit | _ParsedHashlineInsert


@dataclass(frozen=True)
class _PreparedHashlineHunk:
    """One validated hashline hunk prepared for a file-level edit."""

    input_index: int
    path_obj: Path
    relative_path: str
    start_line: int
    end_line: int
    replacement_lines: tuple[str, ...]


@dataclass(frozen=True)
class _HashlineFileSnapshot:
    """Original file state shared by all hunks targeting one file."""

    path_obj: Path
    relative_path: str
    original: str
    original_lines: tuple[str, ...]
    current_sha256: str


def _hashline_replacement_text(lines: Sequence[str]) -> str:
    """Convert plus-prefixed hashline payload rows into edit_lines replacement text."""
    if not lines:
        return ""
    text = "\n".join(lines)
    if lines[-1] == "":
        text += "\n"
    return text


def _hashline_plus_lines(
    lines: Sequence[str], *, require: bool
) -> tuple[str, ...]:
    """Return replacement payload lines after stripping one leading '+'."""
    if require and not lines:
        raise ValueError(
            "hashline edit requires at least one + replacement line"
        )
    for line in lines:
        if not line.startswith("+"):
            raise ValueError("hashline replacement lines must start with '+'")
    return tuple(line[1:] for line in lines)


def _parse_hashline_hunk(
    path: str, snapshot_id: str, body: Sequence[str]
) -> _ParsedHashlineOperation:
    """Parse one non-empty hashline hunk body under a header."""
    if not body:
        raise ValueError("hashline edit input must include an edit hunk")

    swap_match = _HASHLINE_SWAP_RE.match(body[0].strip())
    if swap_match is not None:
        start_line = int(swap_match.group("start"))
        end_line = int(swap_match.group("end") or start_line)
        if end_line < start_line:
            raise ValueError("SWAP end line must be >= start line")
        plus_lines = _hashline_plus_lines(body[1:], require=False)
        return _ParsedHashlineEdit(
            path=path,
            snapshot_id=snapshot_id,
            start_line=start_line,
            end_line=end_line,
            replacement=_hashline_replacement_text(plus_lines),
        )

    insert_match = _HASHLINE_INSERT_RE.match(body[0].strip())
    if insert_match is not None:
        plus_lines = _hashline_plus_lines(body[1:], require=True)
        where = (insert_match.group("where") or "BEFORE").upper()
        return _ParsedHashlineInsert(
            path=path,
            snapshot_id=snapshot_id,
            anchor_line=int(insert_match.group("line")),
            insert_after=where == "AFTER",
            inserted_lines=plus_lines,
        )

    old_lines: list[ReadLine] = []
    replacement_start = len(body)
    for index, line in enumerate(body):
        if line.startswith("+"):
            replacement_start = index
            break
        row_match = _HASHLINE_ROW_RE.match(line)
        if row_match is None:
            raise ValueError(
                "hashline old lines must use '<line>:<text>' rows copied from read/search output"
            )
        old_lines.append(
            ReadLine(
                line=int(row_match.group("line")),
                text=row_match.group("text"),
            )
        )
    if not old_lines:
        raise ValueError("hashline edit must include old lines or a directive")
    expected_line = old_lines[0].line
    for old_line in old_lines:
        if old_line.line != expected_line:
            raise ValueError("hashline old lines must be consecutive")
        expected_line += 1
    plus_lines = _hashline_plus_lines(body[replacement_start:], require=False)
    return _ParsedHashlineEdit(
        path=path,
        snapshot_id=snapshot_id,
        start_line=old_lines[0].line,
        end_line=old_lines[-1].line,
        replacement=_hashline_replacement_text(plus_lines),
        expected_lines=tuple(old_lines),
    )


def parse_hashline_edit_input(
    input_text: str,
) -> tuple[_ParsedHashlineOperation, ...]:
    """Parse the compact hashline edit format accepted by hashline_edit."""
    lines = [line.rstrip("\r") for line in input_text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise ValueError("hashline edit input is empty")

    operations: list[_ParsedHashlineOperation] = []
    current_path: str | None = None
    current_snapshot_id: str | None = None
    current_body: list[str] = []

    def flush_hunk() -> None:
        nonlocal current_body
        if current_path is None or current_snapshot_id is None:
            if current_body:
                raise ValueError(
                    "hashline edit input must start with [path#snapshot_id]"
                )
            return
        if not current_body:
            return
        operations.append(
            _parse_hashline_hunk(
                current_path, current_snapshot_id, current_body
            )
        )
        current_body = []

    for line in lines:
        stripped = line.strip()
        header_match = _HASHLINE_HEADER_RE.match(stripped)
        if header_match is not None:
            flush_hunk()
            current_path = header_match.group("path")
            current_snapshot_id = header_match.group("snapshot")
            continue
        if current_path is None or current_snapshot_id is None:
            raise ValueError(
                "hashline edit input must start with [path#snapshot_id]"
            )
        if not stripped:
            flush_hunk()
            continue
        current_body.append(line)

    flush_hunk()
    if not operations:
        raise ValueError("hashline edit input must include an edit hunk")
    return tuple(operations)


def _path_for_hashline_operation(
    path: str, snapshot_id: str, session_id: str | None
) -> str:
    """Return a path usable by edit_lines, preserving copied read/search headers."""
    if session_id is None:
        return path
    store = get_tool_session_store()
    session = store.touch_session(session_id)
    if session.target != "local":
        return path
    record = store.get_snapshot(session_id, snapshot_id)
    if record is None or record.path != path:
        return path
    candidate = workspace_root() / record.path
    if candidate.exists():
        return str(candidate)
    return path


def _validate_snapshot_for_edit(
    *,
    path: str,
    current_sha256: str,
    start_line: int,
    end_line: int,
    snapshot_id: str | None,
    session_id: str | None,
) -> None:
    """Validate optional snapshot freshness and visible-range grounding."""
    if snapshot_id is None:
        return
    if session_id is None:
        raise ValueError("session_id is required when snapshot_id is provided")
    record = get_tool_session_store().get_snapshot(session_id, snapshot_id)
    if record is None:
        raise ValueError(
            "snapshot_id not found for this session; re-read the file"
        )
    if record.path != path:
        raise ValueError(
            "snapshot_id belongs to a different file; re-read the target file"
        )
    if record.file_sha256 != current_sha256:
        raise ValueError("file changed since snapshot; re-read before editing")
    if record.seen_ranges and not _range_is_visible(
        start_line, end_line, record.seen_ranges
    ):
        raise ValueError(
            "edit range was not shown by the referenced snapshot; re-read the target lines"
        )


def edit_file_execute(
    path: str, old: str, new: str, replace_all: bool = False
) -> EditFileOutput:
    """Replace exact text in a validated text file and report how many occurrences changed."""
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    if p.stat().st_size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to edit {p.stat().st_size} bytes; max is {settings.max_file_write_bytes}"
        )
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ValueError("old text not found")
    if not replace_all and count > 1:
        raise ValueError(
            f"old text occurs {count} times; set replace_all=true or provide more context"
        )
    updated = (
        text.replace(old, new) if replace_all else text.replace(old, new, 1)
    )
    updated_bytes = len(updated.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}"
        )
    p.write_text(updated, encoding="utf-8")
    return EditFileOutput(
        path=relative_display(p), replacements=count if replace_all else 1
    )


def _hashline_file_snapshot(
    path: str, session_id: str | None
) -> _HashlineFileSnapshot:
    """Resolve a hashline path and capture current file state."""
    settings = get_settings()
    store = get_tool_session_store()
    session = (
        store.touch_session(session_id) if session_id is not None else None
    )
    p = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    size = p.stat().st_size
    if size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to edit {size} bytes; max is {settings.max_file_write_bytes}"
        )
    original = p.read_text(encoding="utf-8")
    return _HashlineFileSnapshot(
        path_obj=p,
        relative_path=relative_display(p),
        original=original,
        original_lines=tuple(original.splitlines(keepends=True)),
        current_sha256=file_sha256(p),
    )


def _hashline_operation_range(
    operation: _ParsedHashlineOperation,
) -> tuple[int, int]:
    """Return the original inclusive line range touched by an operation."""
    if isinstance(operation, _ParsedHashlineInsert):
        return operation.anchor_line, operation.anchor_line
    return operation.start_line, operation.end_line


def _prepare_hashline_hunk(
    *,
    input_index: int,
    operation: _ParsedHashlineOperation,
    session_id: str | None,
    snapshots: dict[Path, _HashlineFileSnapshot],
) -> _PreparedHashlineHunk:
    """Validate one parsed hashline hunk and convert it to replacement lines."""
    path_arg = _path_for_hashline_operation(
        operation.path, operation.snapshot_id, session_id
    )
    snapshot = _hashline_file_snapshot(path_arg, session_id)
    snapshots.setdefault(snapshot.path_obj, snapshot)
    snapshot = snapshots[snapshot.path_obj]

    start_line, end_line = _hashline_operation_range(operation)
    if start_line < 1:
        raise ValueError("line numbers must be >= 1")
    if end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    total_lines = len(snapshot.original_lines)
    if end_line > total_lines:
        raise ValueError(
            f"line {end_line} is beyond file line count {total_lines}"
        )

    _validate_snapshot_for_edit(
        path=snapshot.relative_path,
        current_sha256=snapshot.current_sha256,
        start_line=start_line,
        end_line=end_line,
        snapshot_id=operation.snapshot_id,
        session_id=session_id,
    )

    decoded_lines = snapshot.original.splitlines()
    if isinstance(operation, _ParsedHashlineInsert):
        anchor_text = decoded_lines[operation.anchor_line - 1]
        if operation.insert_after:
            replacement_text = _hashline_replacement_text(
                (anchor_text, *operation.inserted_lines)
            )
        else:
            replacement_text = _hashline_replacement_text(
                (*operation.inserted_lines, anchor_text)
            )
    else:
        if operation.expected_lines:
            expected = [line.text for line in operation.expected_lines]
            current = decoded_lines[start_line - 1 : end_line]
            if current != expected:
                raise ValueError(
                    "hashline old text does not match current file; re-read before editing"
                )
        replacement_text = operation.replacement

    selected = snapshot.original_lines[start_line - 1 : end_line]
    replacement_lines = _replacement_lines(
        replacement_text,
        newline=_newline_for_text(snapshot.original),
        selected_had_trailing_newline=bool(
            selected and selected[-1].endswith(("\n", "\r"))
        ),
        has_following_lines=end_line < total_lines,
    )
    return _PreparedHashlineHunk(
        input_index=input_index,
        path_obj=snapshot.path_obj,
        relative_path=snapshot.relative_path,
        start_line=start_line,
        end_line=end_line,
        replacement_lines=tuple(replacement_lines),
    )


def _validate_hashline_hunk_overlap(
    hunks: Sequence[_PreparedHashlineHunk],
) -> None:
    """Reject multiple hunks that touch overlapping original line ranges."""
    by_file: dict[Path, list[_PreparedHashlineHunk]] = {}
    for hunk in hunks:
        by_file.setdefault(hunk.path_obj, []).append(hunk)
    for file_hunks in by_file.values():
        previous: _PreparedHashlineHunk | None = None
        for hunk in sorted(file_hunks, key=lambda item: item.start_line):
            if previous is not None and hunk.start_line <= previous.end_line:
                raise ValueError(
                    "hashline edit hunks overlap; use non-overlapping original line ranges"
                )
            previous = hunk


def _apply_hashline_file_hunks(
    snapshot: _HashlineFileSnapshot,
    hunks: Sequence[_PreparedHashlineHunk],
) -> tuple[tuple[str, ...], str]:
    """Apply prepared hunks to one file and return updated lines plus diff."""
    settings = get_settings()
    updated_lines = list(snapshot.original_lines)
    for hunk in sorted(hunks, key=lambda item: item.start_line, reverse=True):
        updated_lines = (
            updated_lines[: hunk.start_line - 1]
            + list(hunk.replacement_lines)
            + updated_lines[hunk.end_line :]
        )
    updated = "".join(updated_lines)
    updated_bytes = len(updated.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}"
        )

    diff = "".join(
        difflib.unified_diff(
            snapshot.original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=snapshot.relative_path,
            tofile=snapshot.relative_path,
        )
    )
    with snapshot.path_obj.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    return tuple(updated_lines), diff


def _hashline_hunk_contexts(
    *,
    prepared_hunks: Sequence[_PreparedHashlineHunk],
    updated_by_file: dict[Path, tuple[str, ...]],
    snapshots: dict[Path, _HashlineFileSnapshot],
    session_id: str | None,
) -> list[HashlineEditHunkOutput]:
    """Build fresh post-edit context for each hunk in original input order."""
    outputs_by_index: dict[int, HashlineEditHunkOutput] = {}
    by_file: dict[Path, list[_PreparedHashlineHunk]] = {}
    for hunk in prepared_hunks:
        by_file.setdefault(hunk.path_obj, []).append(hunk)

    for path_obj, file_hunks in by_file.items():
        delta = 0
        updated_lines = updated_by_file[path_obj]
        snapshot = snapshots[path_obj]
        for hunk in sorted(file_hunks, key=lambda item: item.start_line):
            new_start = max(1, hunk.start_line + delta)
            replacement_line_count = len(hunk.replacement_lines)
            context_start = max(1, new_start - 3)
            context_end = min(
                len(updated_lines),
                max(
                    new_start,
                    new_start + max(replacement_line_count, 1) + 3,
                ),
            )
            if not updated_lines:
                context_start = context_end = 1
            context = read_file_execute(
                str(snapshot.path_obj), context_start, context_end, session_id
            )
            outputs_by_index[hunk.input_index] = HashlineEditHunkOutput(
                path=hunk.relative_path,
                start_line=hunk.start_line,
                end_line=hunk.end_line,
                replacement_line_count=replacement_line_count,
                context=context,
            )
            delta += replacement_line_count - (
                hunk.end_line - hunk.start_line + 1
            )

    return [
        outputs_by_index[hunk.input_index]
        for hunk in sorted(prepared_hunks, key=lambda item: item.input_index)
    ]


def hashline_edit_execute(
    input_text: str, session_id: str | None = None
) -> HashlineEditOutput:
    """Apply one or more compact hashline edits against original line numbers."""
    operations = parse_hashline_edit_input(input_text)
    snapshots: dict[Path, _HashlineFileSnapshot] = {}
    prepared_hunks = [
        _prepare_hashline_hunk(
            input_index=index,
            operation=operation,
            session_id=session_id,
            snapshots=snapshots,
        )
        for index, operation in enumerate(operations)
    ]
    _validate_hashline_hunk_overlap(prepared_hunks)

    hunks_by_file: dict[Path, list[_PreparedHashlineHunk]] = {}
    for hunk in prepared_hunks:
        hunks_by_file.setdefault(hunk.path_obj, []).append(hunk)

    updated_by_file: dict[Path, tuple[str, ...]] = {}
    diff_parts: list[str] = []
    for path_obj, file_hunks in hunks_by_file.items():
        updated_lines, diff = _apply_hashline_file_hunks(
            snapshots[path_obj], file_hunks
        )
        updated_by_file[path_obj] = updated_lines
        diff_parts.append(diff)

    hunk_outputs = _hashline_hunk_contexts(
        prepared_hunks=prepared_hunks,
        updated_by_file=updated_by_file,
        snapshots=snapshots,
        session_id=session_id,
    )
    first_hunk = hunk_outputs[0]
    first_path = first_hunk.path
    if all(hunk.path == first_path for hunk in hunk_outputs):
        start_line = min(hunk.start_line for hunk in hunk_outputs)
        end_line = max(hunk.end_line for hunk in hunk_outputs)
    else:
        start_line = first_hunk.start_line
        end_line = first_hunk.end_line
    return HashlineEditOutput(
        path=first_path,
        start_line=start_line,
        end_line=end_line,
        replacement_line_count=sum(
            hunk.replacement_line_count for hunk in hunk_outputs
        ),
        diff="".join(diff_parts),
        context=first_hunk.context,
        hunk_count=len(hunk_outputs),
        hunks=hunk_outputs,
    )


def edit_lines_execute(
    path: str,
    start_line: int,
    end_line: int,
    replacement: str,
    snapshot_id: str | None = None,
    session_id: str | None = None,
) -> EditLinesOutput:
    """Replace an inclusive whole-line range with optional snapshot checks."""
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    settings = get_settings()
    store = get_tool_session_store()
    session = (
        store.touch_session(session_id) if session_id is not None else None
    )
    p = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    size = p.stat().st_size
    if size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to edit {size} bytes; max is {settings.max_file_write_bytes}"
        )

    relative_path = relative_display(p)
    current_sha256 = file_sha256(p)
    _validate_snapshot_for_edit(
        path=relative_path,
        current_sha256=current_sha256,
        start_line=start_line,
        end_line=end_line,
        snapshot_id=snapshot_id,
        session_id=session_id,
    )

    original = p.read_text(encoding="utf-8")
    original_lines = original.splitlines(keepends=True)
    total_lines = len(original_lines)
    if end_line > total_lines:
        raise ValueError(
            f"end_line {end_line} is beyond file line count {total_lines}"
        )

    selected = original_lines[start_line - 1 : end_line]
    replacement_lines = _replacement_lines(
        replacement,
        newline=_newline_for_text(original),
        selected_had_trailing_newline=bool(
            selected and selected[-1].endswith(("\n", "\r"))
        ),
        has_following_lines=end_line < total_lines,
    )
    updated_lines = (
        original_lines[: start_line - 1]
        + replacement_lines
        + original_lines[end_line:]
    )
    updated = "".join(updated_lines)
    updated_bytes = len(updated.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}"
        )

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=relative_path,
            tofile=relative_path,
        )
    )
    with p.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)

    replacement_line_count = len(replacement_lines)
    context_start = max(1, start_line - 3)
    context_end = min(
        len(updated_lines),
        max(start_line, start_line + max(replacement_line_count, 1) + 3),
    )
    context = read_file_execute(str(p), context_start, context_end, session_id)
    return EditLinesOutput(
        path=relative_path,
        start_line=start_line,
        end_line=end_line,
        replacement_line_count=replacement_line_count,
        diff=diff,
        context=context,
    )


async def hashline_edit_dispatch_execute(
    input_text: str, session_id: str | None = None
) -> HashlineEditOutput:
    """Dispatch hashline_edit to a local or remote session."""
    if session_id is None:
        return hashline_edit_execute(input_text, session_id)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "hashline_edit",
            {"input": input_text},
        )
        return HashlineEditOutput.model_validate(data)
    return hashline_edit_execute(input_text, session_id)


async def edit_lines_dispatch_execute(
    path: str,
    start_line: int,
    end_line: int,
    replacement: str,
    snapshot_id: str | None = None,
    session_id: str | None = None,
) -> EditLinesOutput:
    """Dispatch edit_lines to a local or remote session."""
    if session_id is None:
        return edit_lines_execute(
            path, start_line, end_line, replacement, snapshot_id, session_id
        )
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "edit_lines",
            {
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "replacement": replacement,
                "snapshot_id": snapshot_id,
            },
        )
        return EditLinesOutput.model_validate(data)
    return edit_lines_execute(
        path, start_line, end_line, replacement, snapshot_id, session_id
    )


def multi_edit_file_execute(
    path: str, edits: list[dict]
) -> MultiEditFileOutput:
    """Apply a sequence of exact-text replacements and write the file only after all edits validate."""
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
    if p.stat().st_size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to edit {p.stat().st_size} bytes; max is {settings.max_file_write_bytes}"
        )
    text = p.read_text(encoding="utf-8")
    total = 0
    for edit in edits:
        old = str(edit["old"])
        new = str(edit["new"])
        replace_all = bool(edit.get("replace_all", False))
        count = text.count(old)
        if count == 0:
            raise ValueError(f"old text not found: {old[:80]!r}")
        if not replace_all and count > 1:
            raise ValueError(f"old text occurs {count} times: {old[:80]!r}")
        text = (
            text.replace(old, new) if replace_all else text.replace(old, new, 1)
        )
        total += count if replace_all else 1
    updated_bytes = len(text.encode("utf-8"))
    if updated_bytes > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {updated_bytes} bytes; max is {settings.max_file_write_bytes}"
        )
    p.write_text(text, encoding="utf-8")
    return MultiEditFileOutput(path=relative_display(p), replacements=total)


def delete_file_or_dir_execute(
    path: str, recursive: bool = False, session_id: str | None = None
) -> DeleteFileOrDirOutput:
    """Delete a file or directory after enforcing recursive-directory semantics."""
    session = (
        get_tool_session_store().touch_session(session_id)
        if session_id is not None
        else None
    )
    p = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    if p.is_dir():
        if not recursive:
            raise IsADirectoryError("Set recursive=true to delete a directory")
        shutil.rmtree(p)
        return DeleteFileOrDirOutput(
            path=relative_display(p), deleted="directory"
        )
    p.unlink()
    return DeleteFileOrDirOutput(path=relative_display(p), deleted="file")


async def delete_file_or_dir_dispatch_execute(
    path: str, recursive: bool = False, session_id: str | None = None
) -> DeleteFileOrDirOutput:
    """Dispatch delete_file_or_dir to a local or remote session."""
    if session_id is None:
        return delete_file_or_dir_execute(path, recursive, session_id)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "delete_file_or_dir",
            {
                "path": path,
                "recursive": recursive,
            },
        )
        return DeleteFileOrDirOutput.model_validate(data)
    return delete_file_or_dir_execute(path, recursive, session_id)
