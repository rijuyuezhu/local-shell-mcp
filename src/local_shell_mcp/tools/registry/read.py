"""High-level read tool registry."""

from dataclasses import replace

from ...config.settings import Settings
from ...ops.files_service import FilesService
from ...ops.read import read_execute
from ...schemas.input_models.read import ReadPathArg
from ...schemas.input_models.session import SessionIdArg
from ...schemas.result_models.read import ReadOutput
from ...tools.contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class ReadToolRegistry(DeclarativeToolRegistry):
    """Register the read tool with selector support."""

    name = "read"
    """Registry group name used for tool-surface organization."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        files_service: FilesService | None = None,
    ) -> None:
        super().__init__(settings)
        self._files_service = files_service

    async def _bound_read(
        self,
        session_id: SessionIdArg,
        path: ReadPathArg,
    ) -> ReadOutput:
        if self._files_service is None:
            raise RuntimeError("Files service is not bound")
        return await self._files_service.read(session_id, path)

    def _enabled_tools(self):
        tools = super()._enabled_tools()
        if self._files_service is None:
            return tools
        return tuple(replace(tool, func=self._bound_read) for tool in tools)


read_tool = ReadToolRegistry.get_tool_decorator()


def _read_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read one file or list one directory inside an explicit agent/workspace session with optional selector suffixes in the path. Use this for normal code context when you know one path, especially before hashline_edit. Use search for content discovery across files, tree_view/list_files/glob_search for path discovery, and connector fetch only when consuming an id from workspace_search. Put ranges in the path selector and preserve the hashline output for edits: `[path#snapshot_id]` plus `line:text` rows can be copied directly into hashline_edit. Use edit_lines only when you already have exact structured path/start/end/replacement data. Supported selectors: path:50, path:50-80, path:50+20, path:5-16,960-973, path:raw, path:50-80:raw, and path:5-16,960-973:raw. Comma-separated ranges apply only within the same file, not across multiple files; ranges must be ordered and non-overlapping; call read separately for each file. Current per-file read cap: {settings.max_file_read_bytes} bytes."""


@read_tool(
    http_method="POST",
    http_path="/tools/read",
    description=_read_description,
    annotations="read_only",
    oauth_scopes=("shell:read",),
)
async def read(
    session_id: SessionIdArg,
    path: ReadPathArg,
) -> ReadOutput:
    """Read a file or directory with optional path selector suffixes."""
    return await read_execute(path, session_id)
