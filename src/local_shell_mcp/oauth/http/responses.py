"""OAuth response helpers."""

from collections.abc import Mapping

from authlib.oauth2.rfc6749.errors import OAuth2Error
from starlette.datastructures import URL
from starlette.responses import JSONResponse, RedirectResponse


def oauth_json(data: dict, status_code: int = 200) -> JSONResponse:
    """Return a no-store JSON response."""
    return JSONResponse(
        data, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def oauth_error(exc: OAuth2Error, status_code: int = 400) -> JSONResponse:
    """Serialize an OAuth error as JSON."""
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    return oauth_json(body, status_code=status_code)


def oauth_redirect(
    redirect_uri: str, query: Mapping[str, str]
) -> RedirectResponse:
    """Append query parameters to a redirect URI."""
    location = str(URL(redirect_uri).include_query_params(**query))
    return RedirectResponse(location, status_code=302)
