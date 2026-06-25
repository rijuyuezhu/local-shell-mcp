"""OAuth token endpoint route and bearer-token compatibility exports.

Security model: see ``docs/security.md#oauth-security``. Token exchange binds
authorization codes to client, redirect URI, resource, PKCE, and one-time use.
"""

from typing import Any

from authlib.oauth2.rfc6749.errors import OAuth2Error
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.service import _prune_codes, exchange_authorization_code
from ..protocol.token_codec import issue_access_token, validate_bearer_token
from .responses import oauth_error, oauth_json

__all__ = [
    "_prune_codes",
    "exchange_authorization_code",
    "issue_access_token",
    "token_endpoint",
    "validate_bearer_token",
]


async def token_endpoint(request: Request) -> JSONResponse:
    """Exchange an authorization code for an access token after service-level grant checks."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    try:
        token_response = exchange_authorization_code(params)
    except OAuth2Error as exc:
        return oauth_error(exc)

    body: dict[str, Any] = {
        "access_token": token_response.access_token,
        "token_type": token_response.token_type,
        "scope": token_response.scope,
    }
    if token_response.expires_in is not None:
        body["expires_in"] = token_response.expires_in
    return oauth_json(body)
