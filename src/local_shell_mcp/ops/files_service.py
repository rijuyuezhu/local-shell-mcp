"""Explicit operation-level orchestration for the Files vertical."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditLinesOutput,
    HashlineEditOutput,
    ListFilesOutput,
    ReadFileMetadata,
    WriteFileOutput,
)
from ..schemas.result_models.read import ReadOutput
from ..tool_session.bindings import (
    RemoteSessionBinding,
    SessionBinding,
)
from ..tool_session.resolver import SessionResolver
from ..tool_session.selectors import parse_read_target
from ..tool_session.store import ToolSessionStore
from .files import (
    FilesConfig,
    _delete_file_or_dir_local,
    _edit_lines_local,
    _hashline_edit_local,
    _list_files_local,
    _read_file_local,
    _write_file_local,
)

type RemoteFilesCall = Callable[
    [RemoteSessionBinding, str, dict[str, Any]], Awaitable[dict[str, Any]]
]


@dataclass(frozen=True)
class RemoteFilesClient:
    """Narrow controller capability for calling one remote Files operation."""

    call: RemoteFilesCall
    """Invoke one worker-side Files tool for an admitted remote binding."""


class FilesService:
    """Route one Files operation from a fresh authoritative session binding."""

    def __init__(
        self,
        config: FilesConfig,
        store: ToolSessionStore,
        *,
        remote: RemoteFilesClient | None,
    ) -> None:
        self.config = config
        self.store = store
        self.sessions = SessionResolver(store)
        self.remote = remote

    def _binding(self, session_id: str) -> SessionBinding:
        return self.sessions.resolve_active_binding(session_id)

    async def _call_remote(
        self,
        binding: RemoteSessionBinding,
        tool: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        if self.remote is None:
            raise RuntimeError("remote Files execution is not available")
        return await self.remote.call(binding, tool, args)

    async def list_files(
        self,
        session_id: str,
        path: str = ".",
        recursive: bool = False,
        max_entries: int = 500,
    ) -> ListFilesOutput:
        """List a directory from one admitted local or remote binding."""
        binding = self._binding(session_id)
        if isinstance(binding, RemoteSessionBinding):
            data = await self._call_remote(
                binding,
                "list_files",
                {
                    "path": path,
                    "recursive": recursive,
                    "max_entries": max_entries,
                },
            )
            return ListFilesOutput.model_validate(data)
        return _list_files_local(
            self.config, binding, path, recursive, max_entries
        )

    async def write_file(
        self,
        session_id: str,
        path: str,
        content: str,
        overwrite: bool = True,
        expected_sha256: str | None = None,
    ) -> WriteFileOutput:
        """Write a file from one admitted local or remote binding."""
        binding = self._binding(session_id)
        if isinstance(binding, RemoteSessionBinding):
            data = await self._call_remote(
                binding,
                "write_file",
                {
                    "path": path,
                    "content": content,
                    "overwrite": overwrite,
                    "expected_sha256": expected_sha256,
                },
            )
            return WriteFileOutput.model_validate(data)
        return _write_file_local(
            self.config,
            binding,
            path,
            content,
            overwrite,
            expected_sha256,
        )

    async def edit_lines(
        self,
        session_id: str,
        path: str,
        start_line: int,
        end_line: int,
        replacement: str,
        snapshot_id: str | None = None,
    ) -> EditLinesOutput:
        """Edit a grounded line range from one admitted binding."""
        binding = self._binding(session_id)
        if isinstance(binding, RemoteSessionBinding):
            data = await self._call_remote(
                binding,
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
        return _edit_lines_local(
            self.config,
            self.store,
            binding,
            path,
            start_line,
            end_line,
            replacement,
            snapshot_id,
        )

    async def hashline_edit(
        self, session_id: str, input_text: str
    ) -> HashlineEditOutput:
        """Apply grounded hashline edits from one admitted binding."""
        binding = self._binding(session_id)
        if isinstance(binding, RemoteSessionBinding):
            data = await self._call_remote(
                binding, "hashline_edit", {"input": input_text}
            )
            return HashlineEditOutput.model_validate(data)
        return _hashline_edit_local(
            self.config, self.store, binding, input_text
        )

    async def delete_file_or_dir(
        self,
        session_id: str,
        path: str,
        recursive: bool = False,
    ) -> DeleteFileOrDirOutput:
        """Delete a file or directory from one admitted binding."""
        binding = self._binding(session_id)
        if isinstance(binding, RemoteSessionBinding):
            data = await self._call_remote(
                binding,
                "delete_file_or_dir",
                {"path": path, "recursive": recursive},
            )
            return DeleteFileOrDirOutput.model_validate(data)
        return _delete_file_or_dir_local(self.config, binding, path, recursive)

    async def read(self, session_id: str, path: str) -> ReadOutput:
        """Read a file or directory with selector semantics from one binding."""
        binding = self._binding(session_id)
        if isinstance(binding, RemoteSessionBinding):
            data = await self._call_remote(binding, "read", {"path": path})
            return ReadOutput.model_validate(data)

        target = parse_read_target(path)
        listed: ListFilesOutput | None = None
        if not target.raw and not target.line_ranges:
            try:
                listed = _list_files_local(
                    self.config, binding, target.path, False, 500
                )
            except NotADirectoryError:
                listed = None
        if listed is not None:
            content_lines = [
                f"{entry.type}\t{entry.path}" for entry in listed.entries
            ]
            if listed.is_truncated:
                content_lines.append("[listing truncated]")
            return ReadOutput(
                kind="directory",
                path=target.path,
                raw=target.raw,
                content="\n".join(content_lines),
                directory=listed,
            )

        file_result = _read_file_local(
            self.config,
            self.store,
            binding,
            target.path,
            target.start_line,
            target.end_line,
            target.line_ranges or None,
        )
        return ReadOutput(
            kind="file",
            path=file_result.path,
            raw=target.raw,
            content=(
                file_result.content
                if target.raw
                else file_result.numbered_content
            ),
            file=ReadFileMetadata.from_read_result(file_result),
        )
