"""Worker-side composition for the migrated Search vertical."""

from typing import Any, cast

from ..config.settings import Settings
from ..ops.search.composition import build_search_service
from ..ops.search.core import SearchPaths
from ..tool_session.store import ToolSessionStore
from .dispatch import WorkerDispatcher, build_worker_dispatcher


def build_worker_dispatcher_with_search(
    settings: Settings, store: ToolSessionStore
) -> WorkerDispatcher:
    """Bind worker-local Search through the Phase 2 dispatcher seam."""
    search_service = build_search_service(settings, store, remote=None)

    async def search_handler(args: dict[str, Any]) -> Any:
        max_results = args.get("max_results")
        return await search_service.search(
            str(args["session_id"]),
            str(args["pattern"]),
            cast(SearchPaths, args.get("paths")),
            bool(args.get("regex", True)),
            bool(args.get("case_sensitive", True)),
            int(max_results) if max_results is not None else None,
            int(args.get("skip") or 0),
            bool(args.get("gitignore", True)),
        )

    return build_worker_dispatcher(handler_overrides={"search": search_handler})
