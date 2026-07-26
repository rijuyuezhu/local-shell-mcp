"""Session-bound local and remote audit query operations."""

import asyncio
from typing import Any

from ...audit import current_audit_call_id, get_audit_entry, query_audit
from ...ops.utils.remote_session import call_remote_session_tool
from ...tool_session.store import get_tool_session_store
from ..schemas.result_models.audit import AuditTailOutput


def _query_args(
    *,
    limit: int,
    event: str | None,
    operation: str | None,
    audit_session: str | None,
    search: str | None,
    start_ts: float | None,
    end_ts: float | None,
    sort: str,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "event": event,
        "operation": operation,
        "session": audit_session,
        "search": search,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "sort": sort,
    }


async def audit_tail_execute(
    session_id: str,
    limit: int = 100,
    event: str | None = None,
    operation: str | None = None,
    audit_session: str | None = None,
    search: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    sort: str = "desc",
    entry_id: str | None = None,
    include_full_payloads: bool = False,
) -> AuditTailOutput:
    """Query one target's coalesced audit stream through an explicit agent session."""
    if include_full_payloads and entry_id is None:
        raise ValueError("include_full_payloads requires entry_id")
    session = get_tool_session_store().touch_session(session_id)
    exclude_call_id = (
        current_audit_call_id() if session.target == "local" else None
    )
    remote_audit_session = audit_session
    if (
        session.target == "remote"
        and audit_session == session.session_id
        and session.worker_session_id
    ):
        remote_audit_session = session.worker_session_id

    if entry_id is not None:
        args = {
            "id": entry_id,
            "include_full_payloads": include_full_payloads,
        }
        if session.target == "remote":
            entry = await call_remote_session_tool(
                session, "get_audit_entry", args
            )
        else:
            entry = await asyncio.to_thread(
                get_audit_entry,
                entry_id,
                include_full_payloads=include_full_payloads,
                exclude_call_id=exclude_call_id,
            )
        failed = int(
            entry.get("ok") is False
            or str(entry.get("status") or "") == "failed"
        )
        data: dict[str, Any] = {
            "entries": [entry],
            "count": 1,
            "total_matched": 1,
            "failed_matched": failed,
        }
    else:
        args = _query_args(
            limit=limit,
            event=event,
            operation=operation,
            audit_session=remote_audit_session,
            search=search,
            start_ts=start_ts,
            end_ts=end_ts,
            sort=sort,
        )
        if session.target == "remote":
            data = await call_remote_session_tool(session, "query_audit", args)
        else:
            data = await asyncio.to_thread(
                query_audit,
                **args,
                exclude_call_id=exclude_call_id,
            )

    return AuditTailOutput(
        session_id=session.session_id,
        target=session.target,
        machine=session.machine,
        entries=list(data.get("entries") or []),
        count=int(data.get("count") or 0),
        total_matched=int(data.get("total_matched") or 0),
        failed_matched=int(data.get("failed_matched") or 0),
        entry_id=entry_id,
        full_payloads=include_full_payloads,
    )
