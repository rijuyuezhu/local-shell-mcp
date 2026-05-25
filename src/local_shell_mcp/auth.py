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
    # Cloudflare Access sends this header to the origin. Authorization: Bearer is useful for tests.
    token = request.headers.get("cf-access-jwt-assertion")
    if token:
        return token
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
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
        raise HTTPException(status_code=403, detail="Cloudflare Access token has no email claim")
    normalized = email.lower()
    if settings.cf_access_allowed_emails and normalized in {
        x.lower() for x in settings.cf_access_allowed_emails
    }:
        return
    if settings.cf_access_allowed_email_domains:
        domain = normalized.split("@")[-1]
        if domain in {x.lower().lstrip("@") for x in settings.cf_access_allowed_email_domains}:
            return
    raise HTTPException(status_code=403, detail="Email is not allowed")


def verify_request(request: Request) -> Principal:
    settings = get_settings()
    if settings.auth_mode == "none":
        return Principal(email=None, subject="anonymous", claims={"auth": "none"})

    if settings.auth_bypass_localhost and _is_localhost(request):
        return Principal(email="localhost", subject="localhost", claims={"auth": "localhost-bypass"})

    if settings.auth_mode != "cloudflare_access":
        raise HTTPException(status_code=500, detail=f"Unsupported auth_mode: {settings.auth_mode}")

    if not settings.cf_access_team_domain or not settings.cf_access_audience:
        raise HTTPException(
            status_code=500,
            detail="Cloudflare Access auth requires cf_access_team_domain and cf_access_audience",
        )

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
    principal = Principal(email=email, subject=claims.get("sub"), claims=claims)
    audit("auth_ok", email=email, path=str(request.url.path), ip=_client_host(request))
    return principal


class CloudflareAccessMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for Cloudflare Access JWT verification.

    This middleware is optional if Cloudflare Access is already enforcing access at the edge, but it
    prevents direct-origin bypass when your endpoint is reachable without Access.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path in {"/healthz", "/readyz"}:
            return await call_next(request)
        try:
            request.state.principal = verify_request(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)
