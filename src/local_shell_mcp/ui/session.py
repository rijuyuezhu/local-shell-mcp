"""Persistent, purpose-isolated Human UI browser sessions."""

import hashlib
import hmac
import ipaddress
import secrets
import time
from typing import Any
from urllib.parse import urlparse

import idna
import jwt

from ..config.settings import get_settings
from ..oauth.core.security import oauth_signing_secret
from ..oauth.core.urls import base_url, issuer_url

UI_SESSION_COOKIE_PREFIX = "local-shell-mcp-ui-session"
UI_CSRF_COOKIE_PREFIX = "local-shell-mcp-ui-csrf"
UI_CSRF_HEADER = "x-local-shell-mcp-ui-csrf"
UI_SESSION_BINDING_HEADER = "x-local-shell-mcp-ui-binding"
UI_SESSION_BINDING_PROTOCOL_PREFIX = "lsm-ui-binding."
UI_SESSION_BINDING_STORAGE_KEY = "local-shell-mcp-ui-session-binding"
UI_SESSION_ESTABLISHED_STORAGE_KEY = "local-shell-mcp-ui-session-established"
UI_SESSION_UNBOUNDED_SOURCE_TTL_S = 30 * 24 * 60 * 60
UI_SESSION_TOKEN_USE = "human-ui-session"
_UI_SESSION_BINDING_MIN_LENGTH = 43
_UI_SESSION_BINDING_MAX_LENGTH = 128


def _session_signing_key() -> bytes:
    """Derive a signing key that cannot mint or validate OAuth bearer tokens."""
    return hmac.digest(
        oauth_signing_secret().encode("utf-8"),
        b"local-shell-mcp-human-ui-session-v1",
        "sha256",
    )


def ui_session_audience() -> str:
    """Return the audience used exclusively by Human UI session tokens."""
    settings = get_settings()
    return f"{base_url()}{settings.ui_path}"


def canonical_ui_origin(url: str) -> str:
    """Return an origin serialized with browser-compatible URL semantics."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if not scheme or hostname is None:
        raise ValueError("Human UI origin must include a scheme and hostname")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            host = idna.encode(
                hostname,
                uts46=True,
                transitional=False,
            ).decode("ascii")
        except idna.IDNAError as exc:
            raise ValueError("Human UI origin hostname is invalid") from exc
    else:
        host = address.compressed.lower()
        if address.version == 6:
            host = f"[{host}]"

    port = parsed.port
    default_port = {"http": 80, "https": 443}.get(scheme)
    if port is not None and port != default_port:
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def ui_origin() -> str:
    """Return the canonical browser origin configured for the service."""
    return canonical_ui_origin(base_url())


def _ui_cookie_namespace(origin: str) -> str:
    """Return a stable namespace so same-host service ports cannot collide."""
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:12]


def ui_session_cookie_name(origin: str | None = None) -> str:
    """Return the origin-scoped Human UI session cookie name."""
    resolved_origin = (
        ui_origin() if origin is None else canonical_ui_origin(origin)
    )
    return f"{UI_SESSION_COOKIE_PREFIX}-{_ui_cookie_namespace(resolved_origin)}"


def ui_csrf_cookie_name(origin: str | None = None) -> str:
    """Return the origin-scoped Human UI CSRF cookie name."""
    resolved_origin = (
        ui_origin() if origin is None else canonical_ui_origin(origin)
    )
    return f"{UI_CSRF_COOKIE_PREFIX}-{_ui_cookie_namespace(resolved_origin)}"


def is_valid_ui_origin(submitted: str) -> bool:
    """Return whether a submitted browser origin matches the configured origin."""
    if not submitted:
        return False
    try:
        normalized = canonical_ui_origin(submitted)
    except UnicodeError, ValueError:
        return False
    return hmac.compare_digest(normalized, ui_origin())


def _csrf_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_valid_ui_session_binding_token(token: str) -> bool:
    """Return whether an origin-scoped browser binding token is well formed."""
    if (
        not _UI_SESSION_BINDING_MIN_LENGTH
        <= len(token)
        <= _UI_SESSION_BINDING_MAX_LENGTH
    ):
        return False
    return all(
        character.isascii() and (character.isalnum() or character in "-_")
        for character in token
    )


def _binding_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def issue_ui_session(
    claims: dict[str, Any], binding_token: str
) -> tuple[str, str, int | None]:
    """Issue a signed Human UI session token and its double-submit CSRF value."""
    if not is_valid_ui_session_binding_token(binding_token):
        raise ValueError("Invalid Human UI session binding token")
    settings = get_settings()
    now = int(time.time())
    configured_expiry = now + (
        settings.oauth_access_token_ttl_s
        if settings.oauth_access_token_ttl_s > 0
        else UI_SESSION_UNBOUNDED_SOURCE_TTL_S
    )
    source_expiry_value = claims.get("exp")
    source_expiry = (
        int(source_expiry_value)
        if isinstance(source_expiry_value, int | float)
        and not isinstance(source_expiry_value, bool)
        else None
    )
    expires_at = min(
        configured_expiry,
        source_expiry if source_expiry is not None else configured_expiry,
    )
    if expires_at <= now:
        raise jwt.ExpiredSignatureError("OAuth bearer has expired")

    csrf_token = secrets.token_urlsafe(32)
    payload: dict[str, Any] = {
        "iss": issuer_url(),
        "sub": str(claims.get("sub") or "local-user"),
        "aud": ui_session_audience(),
        "iat": now,
        "jti": secrets.token_urlsafe(24),
        "client_id": str(claims.get("client_id") or "human-ui"),
        "scope": str(claims.get("scope") or ""),
        "token_use": UI_SESSION_TOKEN_USE,
        "csrf_sha256": _csrf_digest(csrf_token),
        "binding_sha256": _binding_digest(binding_token),
    }
    max_age = expires_at - now
    payload["exp"] = expires_at
    token = jwt.encode(payload, _session_signing_key(), algorithm="HS256")
    return token, csrf_token, max_age


def validate_ui_session(token: str, binding_token: str) -> dict[str, Any]:
    """Decode and validate a purpose-isolated Human UI session token."""
    claims = jwt.decode(
        token,
        _session_signing_key(),
        algorithms=["HS256"],
        audience=ui_session_audience(),
        issuer=issuer_url(),
        options={
            "require": [
                "iat",
                "aud",
                "iss",
                "sub",
                "client_id",
                "scope",
                "token_use",
                "csrf_sha256",
                "binding_sha256",
            ]
        },
    )
    if claims.get("token_use") != UI_SESSION_TOKEN_USE:
        raise jwt.InvalidTokenError("Invalid Human UI session token use")
    if not is_valid_ui_session_binding_token(binding_token):
        raise jwt.InvalidTokenError("Invalid Human UI session binding")
    expected_binding = str(claims.get("binding_sha256") or "")
    if not expected_binding or not hmac.compare_digest(
        _binding_digest(binding_token), expected_binding
    ):
        raise jwt.InvalidTokenError("Invalid Human UI session binding")
    return claims


def has_valid_ui_csrf_tokens(
    cookie_token: str,
    header_token: str,
    claims: dict[str, Any],
) -> bool:
    """Return whether double-submit CSRF values match signed session claims."""
    if not cookie_token or not header_token:
        return False
    if not hmac.compare_digest(cookie_token, header_token):
        return False
    expected_digest = str(claims.get("csrf_sha256") or "")
    return bool(expected_digest) and hmac.compare_digest(
        _csrf_digest(cookie_token), expected_digest
    )
