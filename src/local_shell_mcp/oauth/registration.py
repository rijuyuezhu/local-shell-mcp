"""OAuth dynamic client registration endpoint.

Security model: see ``docs/security.md#oauth-security``. Registration is
permissive for MCP onboarding; local approval and redirect/resource checks occur
later in the authorization flow.
"""

from __future__ import annotations

import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..audit import audit
from .models import _CLIENTS, OAuthClient
from .responses import _json


async def register_client(request: Request) -> JSONResponse:
    """Accept dynamic client registration and persist the issued client identifier."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    # Docs compliance: dynamic registration is intentionally low-friction, but
    # issues opaque client IDs and relies on later local approval before token
    # issuance.
    client_id = "local-shell-mcp-" + secrets.token_urlsafe(24)
    redirect_uris = [
        str(x) for x in body.get("redirect_uris", []) if isinstance(x, str)
    ]
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
