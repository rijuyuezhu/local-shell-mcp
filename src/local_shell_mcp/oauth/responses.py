"""OAuth JSON response and error serialization helpers.

Security model: see ``docs/security.md#oauth-security``. OAuth responses are
kept cache-resistant because they may contain tokens or discovery metadata.
"""

from authlib.oauth2.rfc6749.errors import (
    InvalidGrantError,
    InvalidRequestError,
    OAuth2Error,
)
from starlette.responses import JSONResponse


def _json(data: dict, status_code: int = 200) -> JSONResponse:
    """Return compact JSON responses with the media type expected by OAuth metadata clients."""
    # Docs compliance: avoid intermediary caching for OAuth JSON responses,
    # especially token and error payloads.
    return JSONResponse(
        data, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def _oauth_error(exc: OAuth2Error, status_code: int = 400) -> JSONResponse:
    """Serialize Authlib OAuth errors in the RFC6749 JSON shape."""
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    return _json(body, status_code=status_code)


def _invalid_request(description: str) -> JSONResponse:
    """Return an Authlib-backed invalid_request response."""
    return _oauth_error(InvalidRequestError(description=description))


def _invalid_grant(description: str) -> JSONResponse:
    """Return an Authlib-backed invalid_grant response."""
    return _oauth_error(InvalidGrantError(description=description))
