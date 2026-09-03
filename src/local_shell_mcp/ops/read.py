"""Compatibility facade for the high-level Read tool."""

from ..schemas.result_models.read import ReadOutput
from .files import _compat_files_dependencies
from .files_service import FilesService, RemoteFilesClient
from .utils.remote_session import call_remote_session_tool


async def read_execute(path: str, session_id: str) -> ReadOutput:
    """Dispatch high-level Read through the explicit Files service."""
    config, store = _compat_files_dependencies()

    async def remote_call(binding, tool, args):
        return await call_remote_session_tool(binding, tool, args)

    service = FilesService(
        config,
        store,
        remote=RemoteFilesClient(call=remote_call),
    )
    return await service.read(session_id, path)
