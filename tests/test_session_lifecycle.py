import asyncio

import pytest

from local_shell_mcp.tool_session import lifecycle


@pytest.mark.asyncio
async def test_session_lifecycle_lock_serializes_and_releases_entry():
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            second_entered.set()

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0)
    assert not second_entered.is_set()

    release_first.set()
    await first_task
    await second_task

    assert second_entered.is_set()
    assert "SESSION1" not in lifecycle._ENTRIES


@pytest.mark.asyncio
async def test_cancelled_lifecycle_waiter_does_not_leak_entry():
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            holder_entered.set()
            await release_holder.wait()

    async def waiter() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            raise AssertionError("cancelled waiter must not enter")

    holder_task = asyncio.create_task(holder())
    await holder_entered.wait()
    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    release_holder.set()
    await holder_task

    assert "SESSION1" not in lifecycle._ENTRIES


@pytest.mark.asyncio
async def test_reset_lifecycle_locks_rejects_active_entries():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with lifecycle.session_lifecycle_lock("SESSION1"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()

    with pytest.raises(RuntimeError, match="while in use"):
        lifecycle.reset_session_lifecycle_locks_for_tests()

    release.set()
    await task
    lifecycle.reset_session_lifecycle_locks_for_tests()
    assert lifecycle._ENTRIES == {}
