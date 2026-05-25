from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .audit import audit
from .settings import Settings, get_settings


@dataclass
class Principal:
    email: str | None
    subject: str | None
    claims: dict[str, Any]


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _is_localhost(request: Request) -> bool:
    host = _client_host(request)
    return host in {"127.0.0.1", "::1", "localhost"}


def _extract_token(request: Request) -> str | None:
    # OAuth bearer token. Cloudflare legacy headers are kept for backwards compatibility.
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    token = request.headers.get("cf-access-jwt-assertion")
    if token:
        return token
    cookie_token = request.cookies.get("CF_Authorization")
    if cookie_token:
        return cookie_token
    return None


@lru_cache(maxsize=16)
def _jwk_client(team_domain: str) -> PyJWKClient:
    team_domain = team_domain.removeprefix("https://").rstrip("/")
    return PyJWKClient(f"https://{team_domain}/cdn-cgi/access/certs")


def _check_email(settings: Settings, email: str | None) -> None:
    if not settings.cf_access_allowed_emails and not settings.cf_access_allowed_email_domains:
        return
    if not email:
        raise HTTPException(status_code=403, detail="Token has no email claim")
    normalized = email.lower()
    if settings.cf_access_allowed_emails and normalized in {x.lower() for x in settings.cf_access_allowed_emails}:
        return
    if settings.cf_access_allowed_email_domains:
        domain = normalized.split("@")[-1]
        if domain in {x.lower().lstrip("@") for x in settings.cf_access_allowed_email_domains}:
            return
    raise HTTPException(status_code=403, detail="Email is not allowed")


def _verify_cloudflare_access(request: Request, settings: Settings) -> Principal:
    if not settings.cf_access_team_domain or not settings.cf_access_audience:
        raise HTTPException(status_code=500, detail="Cloudflare Access auth requires team_domain and audience")
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Cloudflare Access JWT")
    try:
        client = _jwk_client(settings.cf_access_team_domain)
        signing_key = client.get_signing_key_from_jwt(token)
        issuer = f"https://{settings.cf_access_team_domain.removeprefix('https://').rstrip('/')}"
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cf_access_audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        audit("auth_failed", error=str(exc), path=str(request.url.path), ip=_client_host(request))
        raise HTTPException(status_code=401, detail=f"Invalid Cloudflare Access JWT: {exc}") from exc
    if claims.get("exp") and int(claims["exp"]) < int(time.time()):
        raise HTTPException(status_code=401, detail="Expired Cloudflare Access JWT")
    email = claims.get("email") or claims.get("common_name")
    _check_email(settings, email)
    return Principal(email=email, subject=claims.get("sub"), claims=claims)


def _verify_oauth(request: Request, settings: Settings) -> Principal:
    from .oauth import protected_resource_metadata, validate_bearer_token

    token = _extract_token(request)
    if not token:
        metadata_url = protected_resource_metadata(request)["resource"].rstrip("/") + "/.well-known/oauth-protected-resource"
        raise HTTPException(
            status_code=401,
            detail="Missing OAuth bearer token",
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}", scope="shell:execute"'},
        )
    try:
        claims = validate_bearer_token(token, request)
    except jwt.PyJWTError as exc:
        audit("oauth_auth_failed", error=str(exc), path=str(request.url.path), ip=_client_host(request))
        raise HTTPException(status_code=401, detail=f"Invalid OAuth bearer token: {exc}") from exc
    return Principal(email=None, subject=claims.get("sub"), claims=claims)


def verify_request(request: Request) -> Principal:
    settings = get_settings()
    if settings.auth_mode == "none":
        return Principal(email=None, subject="anonymous", claims={"auth": "none"})
    if settings.auth_bypass_localhost and _is_localhost(request) and settings.mode == "http":
        return Principal(email="localhost", subject="localhost", claims={"auth": "localhost-bypass"})
    if settings.auth_mode == "oauth":
        principal = _verify_oauth(request, settings)
    elif settings.auth_mode == "cloudflare_access":
        principal = _verify_cloudflare_access(request, settings)
    else:
        raise HTTPException(status_code=500, detail=f"Unsupported auth_mode: {settings.auth_mode}")
    audit("auth_ok", subject=principal.subject, path=str(request.url.path), ip=_client_host(request))
    return principal


class AuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for OAuth bearer verification or legacy Cloudflare Access verification."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if (
            path in {"/healthz", "/readyz", "/docs", "/openapi.json"}
            or path.startswith("/.well-known/")
            or path.startswith("/oauth/")
        ):
            return await call_next(request)
        try:
            request.state.principal = verify_request(request)
        except HTTPException as exc:
            headers = getattr(exc, "headers", None) or {}
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)
        return await call_next(request)


# Backwards-compatible alias.
CloudflareAccessMiddleware = AuthMiddleware
