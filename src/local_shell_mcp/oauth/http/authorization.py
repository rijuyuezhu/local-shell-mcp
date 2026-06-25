"""OAuth authorization endpoint, local approval form, and code issuance.

Security model: see ``docs/security.md#oauth-security``. Authorization requests
are validated before rendering local approval UI or issuing one-time codes.
"""

import hmac
import html as html_lib
from functools import lru_cache
from importlib.resources import files
from xml.sax.saxutils import quoteattr

from authlib.oauth2.rfc6749.errors import OAuth2Error
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from ...audit import audit
from ...config.settings import get_settings
from ..core.models import _CLIENTS
from ..core.service import (
    issue_authorization_response,
    oauth_error_message,
    validate_authorization_request,
)
from ..core.urls import _default_scope, resource_url
from .responses import oauth_redirect

_AUTHORIZE_TEMPLATE = "authorize.html"


@lru_cache(maxsize=1)
def _authorize_template() -> str:
    """Read the package HTML template used by the local approval form."""
    return (
        files("local_shell_mcp.oauth.http")
        .joinpath(_AUTHORIZE_TEMPLATE)
        .read_text(encoding="utf-8")
    )


def _hidden_inputs(params: dict[str, str]) -> str:
    """Preserve validated authorization parameters as hidden fields in the approval form."""

    return "\n".join(
        f'<input type="hidden" name={quoteattr(k)} value={quoteattr(v)} />'
        for k, v in params.items()
    )


def _authorize_form(
    params: dict[str, str], error: str | None = None
) -> HTMLResponse:
    """Render the local approval form used before issuing an authorization code."""
    settings = get_settings()
    scope = params.get("scope") or _default_scope()
    resource = params.get("resource") or resource_url()
    redirect_uri = params.get("redirect_uri") or ""
    client = _CLIENTS.get(params.get("client_id", ""))
    client_name = (
        client.client_name
        if client and client.client_name
        else "Unknown client"
    )
    client_id = params.get("client_id") or ""
    error_html = (
        f'<p style="color:#b00020">{html_lib.escape(error)}</p>'
        if error
        else ""
    )
    pin_hint = "Enter LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN to approve this ChatGPT connector."
    if not settings.oauth_admin_pin:
        pin_hint = "No admin PIN is configured. Set LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN before OAuth approval can continue."
    html = (
        _authorize_template()
        .replace("{{CLIENT_NAME}}", html_lib.escape(client_name))
        .replace("{{CLIENT_ID}}", html_lib.escape(client_id))
        .replace("{{REDIRECT_URI}}", html_lib.escape(redirect_uri))
        .replace("{{RESOURCE}}", html_lib.escape(resource))
        .replace("{{SCOPE}}", html_lib.escape(scope))
        .replace("{{ERROR_HTML}}", error_html)
        .replace("{{HIDDEN_INPUTS}}", _hidden_inputs(params))
        .replace("{{PIN_HINT}}", html_lib.escape(pin_hint))
    )
    return HTMLResponse(html)


async def authorize_get(request: Request) -> Response:
    """Validate authorization input and render the approval form for the local user."""
    params = {k: v for k, v in request.query_params.items()}
    try:
        validate_authorization_request(params)
    except OAuth2Error as exc:
        return _authorize_form(params, error=oauth_error_message(exc))
    return _authorize_form(params)


async def authorize_post(request: Request) -> Response:
    """Issue an authorization code after form approval and redirect the client back."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items() if k != "pin"}
    try:
        auth_request = validate_authorization_request(params)
    except OAuth2Error as exc:
        return _authorize_form(params, error=oauth_error_message(exc))

    settings = get_settings()
    expected_pin = settings.oauth_admin_pin
    submitted_pin = str(form.get("pin") or "")
    # Docs compliance: a configured admin PIN is required before issuing local
    # approval codes; use a constant-time comparison for failed attempts.
    if not expected_pin:
        audit("oauth_pin_missing", client_id=params.get("client_id"))
        return _authorize_form(
            params,
            error="Admin PIN is required before OAuth approval can continue",
        )
    if not hmac.compare_digest(submitted_pin, expected_pin):
        audit("oauth_pin_failed", client_id=params.get("client_id"))
        return _authorize_form(params, error="Invalid admin PIN")

    authorization_response = issue_authorization_response(auth_request)
    return oauth_redirect(
        authorization_response.redirect_uri, authorization_response.query
    )
