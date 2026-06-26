"""OAuth dynamic client registration endpoint."""

from authlib.oauth2.rfc6749.errors import OAuth2Error
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.service import register_dynamic_client
from .requests import parse_registration_request
from .responses import oauth_error, oauth_json


async def register_client(request: Request) -> JSONResponse:
    """Accept dynamic client registration and persist the issued client identifier."""
    try:
        registration_request = await parse_registration_request(request)
        client = register_dynamic_client(registration_request)
    except OAuth2Error as exc:
        return oauth_error(exc)

    return oauth_json(
        {
            "client_id": client.client_id,
            "client_id_issued_at": client.created_at,
            "client_name": client.client_name or "ChatGPT",
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )
