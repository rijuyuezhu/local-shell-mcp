"""OAuth dynamic client registration endpoint.

Security model: see ``docs/security.md#oauth-security``. Registration is
permissive for MCP onboarding; local approval and redirect/resource checks occur
later in the authorization flow.
"""

import secrets
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..audit import audit
from .models import _CLIENTS, OAuthClient
from .responses import invalid_request, oauth_json

LOOPBACK_REDIRECT_HOSTS = {"127.0.0.1", "::1", "localhost"}
BLOCKED_REDIRECT_SCHEMES = {"javascript", "data"}


def _is_private_use_redirect_scheme(parsed_scheme: str, netloc: str) -> bool:
    """Return whether a non-HTTP redirect scheme is private-use style."""
    return "." in parsed_scheme and not netloc


def _is_allowed_redirect_uri(uri: str) -> bool:
    """Accept HTTPS, loopback HTTP, and custom private-use redirect URIs."""
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if not scheme or scheme in BLOCKED_REDIRECT_SCHEMES:
        return False
    if scheme == "https":
        return bool(parsed.netloc)
    if scheme == "http":
        return parsed.hostname in LOOPBACK_REDIRECT_HOSTS
    return _is_private_use_redirect_scheme(scheme, parsed.netloc)


async def register_client(request: Request) -> JSONResponse:
    """Accept dynamic client registration and persist the issued client identifier."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return invalid_request("Registration payload must be a JSON object")
    raw_redirect_uris = body.get("redirect_uris")
    if not isinstance(raw_redirect_uris, list):
        return invalid_request("redirect_uris must be a non-empty list")
    redirect_uris = [
        value.strip()
        for value in raw_redirect_uris
        if isinstance(value, str) and value.strip()
    ]
    if len(redirect_uris) != len(raw_redirect_uris) or not redirect_uris:
        return invalid_request("redirect_uris must contain non-empty strings")
    if any(not _is_allowed_redirect_uri(uri) for uri in redirect_uris):
        return invalid_request(
            "redirect_uris must be https, loopback http, or custom private-use URIs"
        )

    # Docs compliance: dynamic registration is intentionally low-friction, but
    # issues opaque client IDs and relies on later local approval before token
    # issuance.
    client_id = "local-shell-mcp-" + secrets.token_urlsafe(24)
    client = OAuthClient(
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=body.get("client_name")
        if isinstance(body.get("client_name"), str)
        else None,
    )
    _CLIENTS[client_id] = client
    audit(
        "oauth_client_registered",
        client_id=client_id,
        redirect_uris=redirect_uris,
    )
    return oauth_json(
        {
            "client_id": client_id,
            "client_id_issued_at": client.created_at,
            "client_name": client.client_name or "ChatGPT",
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )
