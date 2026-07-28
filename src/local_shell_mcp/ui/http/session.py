"""Human UI OAuth-to-cookie session endpoints."""

import jwt
from authlib.oauth2.rfc6749.errors import OAuth2Error
from fastapi import HTTPException
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response

from ...audit import audit
from ...oauth.core.service import exchange_authorization_code
from ...oauth.core.urls import base_url
from ...oauth.http.auth import verify_oauth
from ...oauth.http.requests import parse_token_request
from ...oauth.http.responses import oauth_error
from ...oauth.protocol.token_codec import validate_bearer_token
from ..session import (
    UI_CSRF_HEADER,
    UI_SESSION_BINDING_HEADER,
    UI_SESSION_BINDING_PROTOCOL_PREFIX,
    has_valid_ui_csrf_tokens,
    is_valid_ui_origin,
    is_valid_ui_session_binding_token,
    issue_ui_session,
    ui_csrf_cookie_name,
    ui_session_cookie_name,
    validate_ui_session,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def has_valid_ui_origin(connection: HTTPConnection) -> bool:
    """Return whether a request or WebSocket has the configured browser origin."""
    return is_valid_ui_origin(connection.headers.get("origin", ""))


def ui_session_binding_token(connection: HTTPConnection) -> str:
    """Return the origin-scoped companion token from HTTP or WebSocket input."""
    header_token = connection.headers.get(UI_SESSION_BINDING_HEADER, "").strip()
    if header_token:
        return header_token
    protocols = connection.headers.get("sec-websocket-protocol", "")
    for protocol in protocols.split(","):
        normalized = protocol.strip()
        if normalized.startswith(UI_SESSION_BINDING_PROTOCOL_PREFIX):
            return normalized.removeprefix(UI_SESSION_BINDING_PROTOCOL_PREFIX)
    return ""


def ui_session_claims(connection: HTTPConnection) -> dict[str, object] | None:
    """Return validated Human UI session claims, or None without a cookie."""
    token = connection.cookies.get(ui_session_cookie_name(), "").strip()
    if not token:
        return None
    return validate_ui_session(token, ui_session_binding_token(connection))


def has_valid_ui_csrf(
    connection: HTTPConnection, claims: dict[str, object]
) -> bool:
    """Return whether an unsafe cookie-authenticated request passes CSRF checks."""
    method = str(connection.scope.get("method") or "GET").upper()
    if method in _SAFE_METHODS:
        return True
    if not has_valid_ui_origin(connection):
        return False
    return has_valid_ui_csrf_tokens(
        connection.cookies.get(ui_csrf_cookie_name(), "").strip(),
        connection.headers.get(UI_CSRF_HEADER, "").strip(),
        claims,
    )


def _cookie_secure() -> bool:
    return base_url().lower().startswith("https://")


def set_ui_session_cookies(
    response: Response, claims: dict[str, object], binding_token: str
) -> int | None:
    """Attach persistent HttpOnly session and readable CSRF cookies."""
    session_token, csrf_token, max_age = issue_ui_session(claims, binding_token)
    cookie_options = {
        "path": "/",
        "secure": _cookie_secure(),
        "samesite": "strict",
        "max_age": max_age,
    }
    response.set_cookie(
        ui_session_cookie_name(),
        session_token,
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        ui_csrf_cookie_name(),
        csrf_token,
        httponly=False,
        **cookie_options,
    )
    return max_age


def clear_ui_session_cookies(response: Response) -> None:
    """Expire both Human UI browser cookies."""
    response.delete_cookie(ui_session_cookie_name(), path="/")
    response.delete_cookie(ui_csrf_cookie_name(), path="/")


def _json_ok(data: object = None, message: str = "") -> JSONResponse:
    return JSONResponse(
        {"ok": True, "message": message, "data": data},
        headers={"Cache-Control": "no-store"},
    )


def _json_error(detail: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "detail": detail},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _require_origin(request: Request) -> Response | None:
    if has_valid_ui_origin(request):
        return None
    return _json_error("Invalid Human UI origin", status_code=403)


def _require_binding(request: Request) -> tuple[str, Response | None]:
    binding_token = ui_session_binding_token(request)
    if is_valid_ui_session_binding_token(binding_token):
        return binding_token, None
    return "", _json_error("Invalid Human UI session binding", status_code=400)


async def api_ui_session_oauth(request: Request) -> Response:
    """Exchange a PKCE authorization code into HttpOnly Human UI cookies."""
    if error := _require_origin(request):
        return error
    binding_token, binding_error = _require_binding(request)
    if binding_error is not None:
        return binding_error
    try:
        token_request = await parse_token_request(request)
        token_response = exchange_authorization_code(token_request)
    except OAuth2Error as exc:
        return oauth_error(exc)

    claims = validate_bearer_token(token_response.access_token)
    response = _json_ok(
        {"expires_in": token_response.expires_in},
        "Human UI session established",
    )
    expires_in = set_ui_session_cookies(response, claims, binding_token)
    audit(
        "ui_session_issued",
        client_id=claims.get("client_id"),
        subject=claims.get("sub"),
        expires_in=expires_in,
        source="oauth",
    )
    return response


async def api_ui_session_token(request: Request) -> Response:
    """Convert an explicitly supplied OAuth bearer into HttpOnly Human UI cookies."""
    if error := _require_origin(request):
        return error
    binding_token, binding_error = _require_binding(request)
    if binding_error is not None:
        return binding_error
    try:
        claims = verify_oauth(request)
    except HTTPException as exc:
        return _json_error(str(exc.detail), status_code=exc.status_code)

    response = _json_ok(message="Human UI session established")
    expires_in = set_ui_session_cookies(response, claims, binding_token)
    audit(
        "ui_session_issued",
        client_id=claims.get("client_id"),
        subject=claims.get("sub"),
        expires_in=expires_in,
        source="bearer",
    )
    return response


async def api_ui_session_logout(request: Request) -> Response:
    """Clear Human UI cookies after same-origin and CSRF validation."""
    if error := _require_origin(request):
        return error
    try:
        claims = ui_session_claims(request)
    except jwt.PyJWTError:
        claims = None
    if claims is not None and not has_valid_ui_csrf(request, claims):
        return _json_error("Human UI CSRF validation failed", status_code=403)

    response = _json_ok(message="Human UI session cleared")
    clear_ui_session_cookies(response)
    audit(
        "ui_session_cleared",
        client_id=claims.get("client_id") if claims else None,
        subject=claims.get("sub") if claims else None,
    )
    return response
