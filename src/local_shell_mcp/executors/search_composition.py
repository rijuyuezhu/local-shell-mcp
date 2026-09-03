"""Controller-side composition for the migrated Search vertical."""

from ..config.settings import Settings
from ..ops.search.composition import build_search_service
from ..ops.search.service import RemoteSearchClient
from ..ops.utils.remote_session import call_remote_session_tool
from ..remote.manager import RemoteManager
from ..tool_session.store import ToolSessionStore
from ..tools.catalog import ToolCatalog, build_tool_catalog
from ..tools.registry.search import SearchToolRegistry


def build_controller_tool_catalog(
    settings: Settings,
    store: ToolSessionStore,
    remote_manager: RemoteManager,
) -> ToolCatalog:
    """Bind controller Search routing through the Phase 2 catalog seam."""

    async def call_remote_search(binding, tool, args):
        return await call_remote_session_tool(
            binding,
            tool,
            args,
            call_worker=remote_manager.call,
        )

    search_service = build_search_service(
        settings,
        store,
        remote=RemoteSearchClient(call=call_remote_search),
    )

    def search_registry(configured_settings: Settings | None):
        return SearchToolRegistry(
            configured_settings,
            search_service=search_service,
        )

    return build_tool_catalog(
        settings,
        factory_overrides={"search": search_registry},
    )
