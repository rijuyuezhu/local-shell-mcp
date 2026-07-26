"""Capacity limits for stateful Streamable HTTP MCP sessions."""

import asyncio
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ...audit import audit


class McpSessionLimitMiddleware:
    """Reject new stateful MCP sessions once the configured capacity is full."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_manager: Any,
        max_sessions: int,
        mcp_path: str = "/mcp",
    ) -> None:
        self.app = app
        self.session_manager = session_manager
        self.max_sessions = max(1, int(max_sessions))
        self.mcp_path = mcp_path
        self._creation_lock = asyncio.Lock()

    def _is_new_session(self, scope: Scope) -> bool:
        """Return whether this request can create one stateful MCP session."""
        if (
            scope.get("type") != "http"
            or scope.get("path") != self.mcp_path
            or str(scope.get("method") or "").upper() != "POST"
        ):
            return False
        header_names = {
            bytes(name).lower()
            for name, _value in scope.get("headers", ())  # type: ignore[misc]
        }
        return b"mcp-session-id" not in header_names

    def _active_session_count(self) -> int:
        """Count live SDK sessions and discard terminated bookkeeping entries."""
        instances = getattr(self.session_manager, "_server_instances", None)
        if not isinstance(instances, dict):
            return 0
        owners = getattr(self.session_manager, "_session_owners", None)
        for session_id, transport in list(instances.items()):
            if not bool(getattr(transport, "is_terminated", False)):
                continue
            instances.pop(session_id, None)
            if isinstance(owners, dict):
                owners.pop(session_id, None)
        return len(instances)

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Serialize session creation and reject requests beyond capacity."""
        if bool(
            getattr(self.session_manager, "stateless", False)
        ) or not self._is_new_session(scope):
            await self.app(scope, receive, send)
            return

        async with self._creation_lock:
            active_sessions = self._active_session_count()
            if active_sessions >= self.max_sessions:
                audit(
                    "mcp_session_rejected",
                    reason="session_limit",
                    active_sessions=active_sessions,
                    max_sessions=self.max_sessions,
                )
                response = JSONResponse(
                    {
                        "ok": False,
                        "error": "mcp_session_limit",
                        "message": (
                            f"MCP session limit reached: {self.max_sessions}"
                        ),
                        "limit": self.max_sessions,
                    },
                    status_code=429,
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
