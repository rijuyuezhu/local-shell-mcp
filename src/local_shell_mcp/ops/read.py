"""High-level read facade operations built on lower-level file ops."""

from ..schemas.result_models.files import ListFilesOutput
from ..schemas.result_models.read import ReadOutput
from ..tool_session.selectors import parse_read_target
from .files import list_files_execute, read_file_execute


def _directory_content(result: ListFilesOutput) -> str:
    """Return a compact model-facing listing for a directory result."""
    lines = [f"{entry.type}\t{entry.path}" for entry in result.entries]
    if result.is_truncated:
        lines.append("[listing truncated]")
    return "\n".join(lines)


def read_execute(path: str, session_id: str | None = None) -> ReadOutput:
    """Read a file or directory using optional path selector suffixes."""
    target = parse_read_target(path)
    listed = None
    if not target.raw and target.start_line is None and target.end_line is None:
        try:
            listed = list_files_execute(target.path, False, 500)
        except NotADirectoryError:
            listed = None
    if listed is not None:
        return ReadOutput(
            kind="directory",
            path=target.path,
            raw=target.raw,
            content=_directory_content(listed),
            directory=listed,
        )

    file_result = read_file_execute(
        target.path,
        target.start_line,
        target.end_line,
        session_id,
    )
    return ReadOutput(
        kind="file",
        path=file_result.path,
        raw=target.raw,
        content=file_result.content
        if target.raw
        else file_result.numbered_content,
        file=file_result,
    )
