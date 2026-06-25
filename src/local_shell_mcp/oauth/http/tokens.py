"""OAuth token endpoint route.

Security model: see ``docs/security.md#oauth-security``. Token exchange binds
authorization codes to client, redirect URI, resource, PKCE, and one-time use.
"""

from authlib.oauth2.rfc6749.errors import OAuth2Error
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.service import exchange_authorization_code
from .requests import parse_token_request
from .responses import oauth_error, oauth_json


async def token_endpoint(request: Request) -> JSONResponse:
    """Exchange an authorization code for an access token after service-level grant checks."""
    try:
        token_request = await parse_token_request(request)
        token_response = exchange_authorization_code(token_request)
    except OAuth2Error as exc:
        return oauth_error(exc)

    body: dict[str, object] = {
        "access_token": token_response.access_token,
        "token_type": token_response.token_type,
        "scope": token_response.scope,
    }
    if token_response.expires_in is not None:
        body["expires_in"] = token_response.expires_in
    return oauth_json(body)
