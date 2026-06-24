"""Provide workspace-aware UTF-8 file operations with path containment and bounded output."""

import codecs
import difflib
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass

from ..config.settings import get_settings
from ..schemas.input_models.files import ReadFileRequest
from ..schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditFileOutput,
    EditLinesOutput,
    EntryInfo,
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
    selected_lines = _selected_read_lines(all_lines, start_line, end_line)
    if start_line is not None or end_line is not None:
        text = "\n".join(line.text for line in selected_lines)

    start = selected_lines[0].line if selected_lines else None
    end = selected_lines[-1].line if selected_lines else None
    if start is not None and end is not None:
        seen_ranges = ((start, end),)
        seen_range_models = [LineRange(start=start, end=end)]
    else:
        seen_ranges = ()
        seen_range_models = []
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


def _parse_hashline_header(input_text: str) -> tuple[str, str, list[str]]:
    """Parse and remove the [path#snapshot] header from hashline edit input."""
    lines = [line.rstrip("\r") for line in input_text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise ValueError("hashline edit input is empty")
    match = _HASHLINE_HEADER_RE.match(lines[0].strip())
    if match is None:
        raise ValueError(
            "hashline edit input must start with [path#snapshot_id]"
        )
    body = lines[1:]
    if not body:
        raise ValueError("hashline edit input must include an edit hunk")
    return match.group("path"), match.group("snapshot"), body


def parse_hashline_edit_input(input_text: str) -> _ParsedHashlineOperation:
    """Parse the compact hashline edit format accepted by hashline_edit."""
    path, snapshot_id, body = _parse_hashline_header(input_text)

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


def _current_hashline_texts(
    path: str,
    start_line: int,
    end_line: int,
    session_id: str | None,
) -> list[str]:
    """Read current line text for hashline validation or insertion anchoring."""
    store = get_tool_session_store()
    session = (
        store.touch_session(session_id) if session_id is not None else None
    )
    p = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    lines = p.read_text(encoding="utf-8").splitlines()
    if start_line < 1:
        raise ValueError("line numbers must be >= 1")
    if end_line > len(lines):
        raise ValueError(
            f"line {end_line} is beyond file line count {len(lines)}"
        )
    return lines[start_line - 1 : end_line]


def _validate_hashline_expected_lines(
    path: str, expected_lines: Sequence[ReadLine], session_id: str | None
) -> None:
    """Reject direct hashline edits when copied old text no longer matches."""
    if not expected_lines:
        return
    current = _current_hashline_texts(
        path, expected_lines[0].line, expected_lines[-1].line, session_id
    )
    expected = [line.text for line in expected_lines]
    if current != expected:
        raise ValueError(
            "hashline old text does not match current file; re-read before editing"
        )


def _hashline_insert_replacement(
    path: str, operation: _ParsedHashlineInsert, session_id: str | None
) -> str:
    """Build a replacement range for an insert anchored on a visible line."""
    anchor_text = _current_hashline_texts(
        path, operation.anchor_line, operation.anchor_line, session_id
    )[0]
    if operation.insert_after:
        lines = (anchor_text, *operation.inserted_lines)
    else:
        lines = (*operation.inserted_lines, anchor_text)
    return _hashline_replacement_text(lines)


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


def hashline_edit_execute(
    input_text: str, session_id: str | None = None
) -> EditLinesOutput:
    """Apply a compact hashline edit by reusing edit_lines grounding checks."""
    operation = parse_hashline_edit_input(input_text)
    path = _path_for_hashline_operation(
        operation.path, operation.snapshot_id, session_id
    )
    if isinstance(operation, _ParsedHashlineInsert):
        replacement = _hashline_insert_replacement(path, operation, session_id)
        return edit_lines_execute(
            path,
            operation.anchor_line,
            operation.anchor_line,
            replacement,
            operation.snapshot_id,
            session_id,
        )

    _validate_hashline_expected_lines(
        path, operation.expected_lines, session_id
    )
    return edit_lines_execute(
        path,
        operation.start_line,
        operation.end_line,
        operation.replacement,
        operation.snapshot_id,
        session_id,
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
) -> EditLinesOutput:
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
        return EditLinesOutput.model_validate(data)
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
