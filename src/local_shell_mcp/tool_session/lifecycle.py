"""Process-local serialization for session admission and termination."""

import asyncio
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _LifecycleEntry:
    """One loop-local lock with a protected waiter/user count."""

    lock: asyncio.Lock
    users: int = 0


_ENTRIES_LOCK = threading.Lock()
_ENTRIES: dict[str, _LifecycleEntry] = {}


@asynccontextmanager
async def session_lifecycle_lock(session_id: str) -> AsyncGenerator[None]:
    """Serialize job admission, retry, and teardown for one session.

    Entries are removed after the last holder or waiter exits. This avoids both
    unbounded process-local state and reusing an asyncio lock from a prior event
    loop in tests or embedded runtimes.
    """
    with _ENTRIES_LOCK:
        entry = _ENTRIES.get(session_id)
        if entry is None:
            entry = _LifecycleEntry(lock=asyncio.Lock())
            _ENTRIES[session_id] = entry
        entry.users += 1

    acquired = False
    try:
        await entry.lock.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry.lock.release()
        with _ENTRIES_LOCK:
            entry.users -= 1
            if entry.users == 0 and _ENTRIES.get(session_id) is entry:
                _ENTRIES.pop(session_id, None)


def reset_session_lifecycle_locks_for_tests() -> None:
    """Clear idle lifecycle entries between isolated test runtimes."""
    with _ENTRIES_LOCK:
        if any(entry.users for entry in _ENTRIES.values()):
            raise RuntimeError(
                "cannot reset session lifecycle locks while in use"
            )
        _ENTRIES.clear()
