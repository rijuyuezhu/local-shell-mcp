"""OAuth public URL, issuer, resource, and scope helpers.

Security model: see ``docs/security.md#oauth-security``. These helpers define
the canonical issuer/resource values that later metadata and token validation
must use consistently.
"""

from urllib.parse import urlparse, urlunparse

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
    # Docs compliance: OAuth security requires token audience binding to the
    # most specific MCP resource. Use the MCP endpoint, not just the origin, so
    # access tokens are not valid for every service on the same host.
    return (public_base_url(request).rstrip("/") + "/mcp").rstrip("/")


def protected_resource_metadata_url(request: Request | None = None) -> str:
    """Return the RFC9728 metadata URL for the canonical protected resource."""
    parsed = urlparse(resource_url(request))
    path = parsed.path or ""
    if path == "/":
        path = ""
    # Docs compliance: RFC 9728 inserts the well-known protected-resource
    # suffix between the host and the protected resource path/query.
    metadata_path = "/.well-known/oauth-protected-resource" + path
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            metadata_path,
            "",
            parsed.query,
            "",
        )
    )


def _normalize_resource(value: str) -> str:
    """Normalize resource indicators for exact-but-slash-tolerant comparisons."""
    return value.rstrip("/")


def _default_scope() -> str:
    """Return the default local single-user scope grant."""
    return " ".join(_scopes())


def _scopes() -> list[str]:
    """Return the static scopes supported by local-shell-mcp's OAuth flow."""
    return ["shell:read", "shell:write", "shell:execute"]
