"""ASGI middleware for OAuth-protected HTTP and MCP requests."""

from collections.abc import Iterable

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Receive, Scope, Send

from ..core.context import bind_oauth_claims, reset_oauth_claims
from .auth import verify_request


def _public_route_matches(route: BaseRoute, scope: Scope) -> bool:
    """Return whether a configured public route fully matches the request scope."""
    match, _ = route.matches(scope)
    return match is Match.FULL


class AuthMiddleware:
    """ASGI middleware for OAuth bearer verification."""

    def __init__(
        self, app: ASGIApp, *, public_routes: Iterable[BaseRoute] = ()
    ) -> None:
        self.app = app
        self._public_routes = tuple(public_routes)

    def _is_public_scope(self, scope: Scope) -> bool:
        """Return whether a request scope is served by a configured public route."""
        return any(
            _public_route_matches(route, scope) for route in self._public_routes
        )

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Apply public-route bypasses and bearer verification."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._is_public_scope(scope):
            await self.app(scope, receive, send)
            return

        try:
            request = Request(scope, receive)
            claims = verify_request(request)
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=exc.headers or {},
            )
            await response(scope, receive, send)
            return

        claims_token = bind_oauth_claims(claims)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_oauth_claims(claims_token)
