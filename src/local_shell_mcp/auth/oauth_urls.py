"""OAuth public URL, issuer, resource, and scope helpers."""

from __future__ import annotations

from starlette.requests import Request

from ..config.settings import get_settings


def public_base_url(request: Request | None = None) -> str:
    """Determine the externally visible base URL from configured public URL or request headers."""
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request is not None:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc
        )
        return f"{proto}://{host}".rstrip("/")
    return "http://127.0.0.1:8765"


def issuer_url(request: Request | None = None) -> str:
    """Return the OAuth issuer URL advertised in metadata and encoded into access tokens."""
    settings = get_settings()
    return (settings.oauth_issuer or public_base_url(request)).rstrip("/")


def resource_url(request: Request | None = None) -> str:
    """Return the canonical MCP resource URI used for OAuth audience binding."""
    settings = get_settings()
    if settings.oauth_resource:
        return settings.oauth_resource.rstrip("/")
    # Use the MCP endpoint, not just the origin, so access tokens are audience-bound
    # to this server rather than every service on the same host.
    return (public_base_url(request).rstrip("/") + "/mcp").rstrip("/")


def _normalize_resource(value: str) -> str:
    """Normalize resource indicators for exact-but-slash-tolerant comparisons."""
    return value.rstrip("/")


def _default_scope() -> str:
    """Return the default local single-user scope grant."""
    return " ".join(_scopes())


def _scopes() -> list[str]:
    """Return the static scopes supported by local-shell-mcp's OAuth flow."""
    return ["shell:read", "shell:write", "shell:execute"]
