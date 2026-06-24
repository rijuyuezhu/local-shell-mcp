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
from .responses import _invalid_request, _json


async def register_client(request: Request) -> JSONResponse:
    """Accept dynamic client registration and persist the issued client identifier."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return _invalid_request("Registration payload must be a JSON object")
    raw_redirect_uris = body.get("redirect_uris")
    if not isinstance(raw_redirect_uris, list):
        return _invalid_request("redirect_uris must be a non-empty list")
    redirect_uris = [
        value.strip()
        for value in raw_redirect_uris
        if isinstance(value, str) and value.strip()
    ]
    if len(redirect_uris) != len(raw_redirect_uris) or not redirect_uris:
        return _invalid_request("redirect_uris must contain non-empty strings")
    if any(not urlparse(uri).scheme for uri in redirect_uris):
        return _invalid_request("redirect_uris must be absolute URIs")

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
    return _json(
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
