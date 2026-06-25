"""OAuth JSON response and error serialization helpers.

Security model: see ``docs/security.md#oauth-security``. OAuth responses are
kept cache-resistant because they may contain tokens or discovery metadata.
"""

from collections.abc import Mapping

from authlib.oauth2.rfc6749.errors import (
    InvalidGrantError,
    InvalidRequestError,
    OAuth2Error,
)
from starlette.datastructures import URL
from starlette.responses import JSONResponse, RedirectResponse


def oauth_json(data: dict, status_code: int = 200) -> JSONResponse:
    """Return no-store JSON responses for OAuth metadata, token, and error payloads."""
    # Docs compliance: avoid intermediary caching for OAuth JSON responses,
    # especially token and error payloads.
    return JSONResponse(
        data, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def oauth_error(exc: OAuth2Error, status_code: int = 400) -> JSONResponse:
    """Serialize Authlib OAuth errors in the RFC6749 JSON shape."""
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    return oauth_json(body, status_code=status_code)


def invalid_request(description: str) -> JSONResponse:
    """Return an Authlib-backed invalid_request response."""
    return oauth_error(InvalidRequestError(description=description))


def invalid_grant(description: str) -> JSONResponse:
    """Return an Authlib-backed invalid_grant response."""
    return oauth_error(InvalidGrantError(description=description))


def oauth_redirect(
    redirect_uri: str, query: Mapping[str, str]
) -> RedirectResponse:
    """Append OAuth authorization response parameters to a redirect URI."""
    location = str(URL(redirect_uri).include_query_params(**query))
    return RedirectResponse(location, status_code=302)
