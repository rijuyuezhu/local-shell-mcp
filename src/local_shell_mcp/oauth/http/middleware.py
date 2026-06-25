"""Authenticate HTTP and MCP requests while keeping OAuth bootstrap routes public.

Security model: see ``docs/security.md#oauth-security``. This middleware is the
resource-server boundary for tool and MCP requests.
"""

from collections.abc import Iterable
from contextvars import ContextVar
from typing import Any

from authlib.oauth2.rfc6749.errors import MissingAuthorizationError, OAuth2Error
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Receive, Scope, Send

from ...audit import audit
from ...config.settings import get_settings
from ..core.scopes import scope_set
from ..core.urls import protected_resource_metadata_url
from ..protocol.bearer import validate_bearer_request

OAUTH_CLAIMS: ContextVar[dict[str, Any] | None] = ContextVar(
    "local_shell_mcp_oauth_claims", default=None
)


def _public_route_matches(route: BaseRoute, scope: Scope) -> bool:
    """Return whether a configured public route fully matches the request scope."""
    match, _ = route.matches(scope)
    return match is Match.FULL


def _client_host(request: Request) -> str:
    """Extract the peer host from a FastAPI request without failing when client metadata is absent."""
    return request.client.host if request.client else ""


def _is_localhost(request: Request) -> bool:
    """Detect requests eligible for localhost auth bypass in HTTP mode."""
    host = _client_host(request)
    return host in {"127.0.0.1", "::1", "localhost"}


def _bearer_challenge(request: Request, *, error: str | None = None) -> str:
    """Build the OAuth challenge advertised to MCP clients when auth is missing or invalid."""
    # Docs compliance: MCP requires 401 challenges to advertise protected
    # resource metadata through the RFC 9728 ``resource_metadata`` parameter.
    metadata_url = protected_resource_metadata_url(request)
    parts = [f'resource_metadata="{metadata_url}"']
    if error:
        parts.append(f'error="{error}"')
    return "Bearer " + ", ".join(parts)


def _verify_oauth(request: Request) -> dict[str, Any]:
    """Validate an OAuth bearer token and return its claims."""
    try:
        # Docs compliance: inbound bearer tokens must be validated before any
        # tool request is processed, including issuer and audience checks.
        return validate_bearer_request(request)
    except MissingAuthorizationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Missing OAuth bearer token",
            headers={"WWW-Authenticate": _bearer_challenge(request)},
        ) from exc
    except OAuth2Error as exc:
        audit(
            "oauth_auth_failed",
            error=str(exc),
            path=str(request.url.path),
            ip=_client_host(request),
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid OAuth bearer token",
            headers={
                "WWW-Authenticate": _bearer_challenge(
                    request, error="invalid_token"
                )
            },
        ) from exc


def current_oauth_claims() -> dict[str, Any] | None:
    """Return bearer claims for the current protected request, if any."""
    return OAUTH_CLAIMS.get()


def require_oauth_scopes(required_scopes: tuple[str, ...]) -> None:
    """Reject the current request unless its bearer token includes all required scopes."""
    claims = current_oauth_claims()
    if claims is None or not required_scopes:
        return
    granted = scope_set(str(claims.get("scope") or ""))
    missing = [scope for scope in required_scopes if scope not in granted]
    if missing:
        raise HTTPException(
            status_code=403,
            detail=f"Missing required OAuth scope: {missing[0]}",
        )


def verify_request(request: Request) -> dict[str, Any] | None:
    """Verify a request according to configured auth mode and local bypass rules."""
    settings = get_settings()
    match settings.auth_mode:
        case "none":
            return None
        case "oauth" if (
            settings.auth_bypass_localhost
            and _is_localhost(request)
            and settings.mode == "http"
        ):
            return None
        case "oauth":
            claims = _verify_oauth(request)
        case _:
            raise HTTPException(
                status_code=500,
                detail=f"Unsupported auth_mode: {settings.auth_mode}",
            )
    audit(
        "auth_ok",
        subject=claims.get("sub"),
        path=str(request.url.path),
        ip=_client_host(request),
    )
    return claims


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
        """Apply public-route bypasses and bearer verification for protected HTTP requests."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Docs compliance: OAuth discovery and bootstrap endpoints must remain
        # reachable without a bearer token; tool/MCP routes remain protected.
        if self._is_public_scope(scope):
            await self.app(scope, receive, send)
            return

        try:
            request = Request(scope, receive)
            claims = verify_request(request)
        except HTTPException as exc:
            headers = exc.headers or {}
            response = JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=headers,
            )
            await response(scope, receive, send)
            return

        claims_token = OAUTH_CLAIMS.set(claims)
        try:
            await self.app(scope, receive, send)
        finally:
            OAUTH_CLAIMS.reset(claims_token)
