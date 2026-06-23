"""Provide workspace-aware UTF-8 file operations with path containment and bounded output."""

import codecs
import difflib
import shutil
from collections.abc import Sequence

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
from ..tool_session.store import file_sha256, get_tool_session_store
from .utils.path import relative_display, resolve_path


def list_files_execute(
    path: str = ".", recursive: bool = False, max_entries: int = 500
) -> ListFilesOutput:
    """List directory entries up to a limit and report whether results were truncated."""
    settings = get_settings()
    base = resolve_path(path, must_exist=True)
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


def _numbered_content(lines: list[ReadLine]) -> str:
    """Format lines in a stable model-facing line-numbered form."""
    return "\n".join(f"{line.line}|{line.text}" for line in lines)


def read_file_execute(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    session_id: str | None = None,
) -> ReadFileOutput:
    """Read a UTF-8 text file by optional line range and record grounding."""
    settings = get_settings()
    p = resolve_path(path, must_exist=True)
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
    record = get_tool_session_store().record_file_snapshot(
        session_id=session_id,
        path=relative_path,
        file_sha256=file_sha256(p),
        total_lines=total_lines,
        seen_ranges=seen_ranges,
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
        numbered_content=_numbered_content(selected_lines),
        session_id=record.session_id,
        snapshot_id=record.snapshot_id,
        file_sha256=record.file_sha256,
        seen_ranges=seen_range_models,
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
        item = read_file_execute(path, start_line, end_line)
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
    path: str, content: str, overwrite: bool = True
) -> WriteFileOutput:
    """Write a text file after path validation, parent creation, and overwrite checks."""
    settings = get_settings()
    data = content.encode("utf-8")
    if len(data) > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing to write {len(data)} bytes; max is {settings.max_file_write_bytes}"
        )
    p = resolve_path(path)
    if p.exists() and not overwrite:
        raise FileExistsError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    created = not p.exists()
    p.write_text(content, encoding="utf-8")
    return WriteFileOutput(
        path=relative_display(p), bytes=len(data), created=created
    )


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
    p = resolve_path(path, must_exist=True)
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
    context = read_file_execute(
        relative_path, context_start, context_end, session_id
    )
    return EditLinesOutput(
        path=relative_path,
        start_line=start_line,
        end_line=end_line,
        replacement_line_count=replacement_line_count,
        diff=diff,
        context=context,
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
    path: str, recursive: bool = False
) -> DeleteFileOrDirOutput:
    """Delete a file or directory after enforcing recursive-directory semantics."""
    p = resolve_path(path, must_exist=True)
    if p.is_dir():
        if not recursive:
            raise IsADirectoryError("Set recursive=true to delete a directory")
        shutil.rmtree(p)
        return DeleteFileOrDirOutput(
            path=relative_display(p), deleted="directory"
        )
    p.unlink()
    return DeleteFileOrDirOutput(path=relative_display(p), deleted="file")
