"""Controller-side composition for the migrated Search vertical."""

from ..config.settings import Settings
from ..ops.search.composition import build_search_service
from ..ops.search.service import RemoteSearchClient
from ..tool_session.store import ToolSessionStore
from ..tools.catalog import ToolCatalog, build_tool_catalog
from ..tools.registry.search import SearchToolRegistry


def build_controller_tool_catalog(
    settings: Settings, store: ToolSessionStore
) -> ToolCatalog:
    """Bind controller Search routing through the Phase 2 catalog seam."""
    search_service = build_search_service(
        settings,
        store,
        remote=RemoteSearchClient(),
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
