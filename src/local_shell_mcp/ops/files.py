"""Provide workspace-aware UTF-8 file operations with path containment and bounded output."""

import codecs
import shutil
from collections.abc import Sequence

from ..config.settings import get_settings
from ..schemas.input_models.files import ReadFileRequest
from ..schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditFileOutput,
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
