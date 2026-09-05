import pytest

from workgate.remote.tool_specs import (
    REMOTE_WORKER_ORIGIN_ARG,
    REMOTE_WORKER_ORIGIN_HUMAN_UI,
    REMOTE_WORKER_TOOL_NAMES,
)
from workgate.remote_worker.dispatch import (
    WORKER_TOOL_NAMES,
    build_worker_dispatcher,
)


def test_worker_dispatcher_membership_matches_shared_capabilities_exactly() -> (
    None
):
    dispatcher = build_worker_dispatcher()

    assert frozenset(dispatcher.handlers) == REMOTE_WORKER_TOOL_NAMES
    assert WORKER_TOOL_NAMES == REMOTE_WORKER_TOOL_NAMES


def test_worker_dispatchers_are_fresh_and_handler_maps_are_immutable() -> None:
    first = build_worker_dispatcher()
    second = build_worker_dispatcher()

    assert first is not second
    assert first.handlers is not second.handlers
    with pytest.raises(TypeError):
        first.handlers["search"] = first.handlers["search"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_worker_dispatcher_override_binds_search_dependency() -> None:
    dependency = object()

    async def bound_search(args):
        return {
            "dependency": dependency,
            "query": args["query"],
        }

    dispatcher = build_worker_dispatcher(
        handler_overrides={"search": bound_search}
    )

    result = await dispatcher.execute(
        "search",
        {
            REMOTE_WORKER_ORIGIN_ARG: REMOTE_WORKER_ORIGIN_HUMAN_UI,
            "query": "needle",
        },
    )

    assert result == {"dependency": dependency, "query": "needle"}


def test_worker_dispatcher_rejects_unknown_override() -> None:
    async def handler(_args):
        return None

    with pytest.raises(
        ValueError, match="unknown remote worker handler override"
    ):
        build_worker_dispatcher(handler_overrides={"plugin": handler})
