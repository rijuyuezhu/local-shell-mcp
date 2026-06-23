"""Read tool operations built on lower-level file ops."""

from ..schemas.result_models.files import ListFilesOutput, ReadFileMetadata
from ..schemas.result_models.read import ReadOutput
from ..tool_session.selectors import parse_read_target
from ..tool_session.store import get_tool_session_store, resolve_session_path
from .files import list_files_execute, read_file_execute
from .utils.remote_session import call_remote_session_tool


def _directory_content(result: ListFilesOutput) -> str:
    """Return a compact model-facing listing for a directory result."""
    lines = [f"{entry.type}	{entry.path}" for entry in result.entries]
    if result.is_truncated:
        lines.append("[listing truncated]")
    return "\n".join(lines)


async def read_execute(path: str, session_id: str) -> ReadOutput:
    """Read a file or directory using optional path selector suffixes."""
    store = get_tool_session_store()
    session = store.touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(session, "read", {"path": path})
        return ReadOutput.model_validate(data)
    target = parse_read_target(path)
    target_path = str(
        resolve_session_path(session, target.path, must_exist=True)
    )
    listed = None
    if not target.raw and target.start_line is None and target.end_line is None:
        try:
            listed = list_files_execute(target_path, False, 500)
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
        target_path,
        target.start_line,
        target.end_line,
        session.session_id,
    )
    return ReadOutput(
        kind="file",
        path=file_result.path,
        raw=target.raw,
        content=file_result.content
        if target.raw
        else file_result.numbered_content,
        file=ReadFileMetadata.from_read_result(file_result),
    )
