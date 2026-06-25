"""OAuth authorization endpoint, local approval form, and code issuance.

Security model: see ``docs/security.md#oauth-security``. Authorization requests
are validated before rendering local approval UI or issuing one-time codes.
"""

import hmac
import html as html_lib
import secrets
from functools import lru_cache
from importlib.resources import files
from xml.sax.saxutils import quoteattr

from authlib.oauth2.rfc7636.challenge import CODE_CHALLENGE_PATTERN
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from ..audit import audit
from ..config.settings import get_settings
from .models import _CLIENTS, _CODES, AuthCode
from .responses import oauth_redirect
from .scopes import normalize_requested_scope
from .urls import (
    _default_scope,
    _normalize_resource,
    issuer_url,
    resource_url,
)

_AUTHORIZE_TEMPLATE = "authorize.html"


@lru_cache(maxsize=1)
def _authorize_template() -> str:
    """Read the package HTML template used by the local approval form."""
    return (
        files("local_shell_mcp.oauth")
        .joinpath(_AUTHORIZE_TEMPLATE)
        .read_text(encoding="utf-8")
    )


def _validate_authorize_params(params: dict[str, str]) -> str | None:
    """Validate authorization request parameters before rendering the consent form or redirecting."""
    # Docs compliance: this server intentionally supports the authorization
    # code flow only; token/implicit-style authorization responses are rejected.
    if params.get("response_type") != "code":
        return "Only response_type=code is supported"
    if not params.get("client_id"):
        return "Missing client_id"
    if not params.get("redirect_uri"):
        return "Missing redirect_uri"
    if not params.get("resource"):
        return "Missing resource"
    # Docs compliance: MCP clients must send RFC 8707 ``resource`` and it must
    # match this server before a code can be issued.
    if _normalize_resource(params["resource"]) != resource_url():
        return "resource does not match this MCP server"
    client = _CLIENTS.get(params["client_id"])
    if client is None:
        return "Unknown client_id"
    if params["redirect_uri"] not in client.redirect_uris:
        return "redirect_uri is not registered for this client"
    try:
        normalize_requested_scope(params.get("scope"))
    except ValueError as exc:
        return str(exc)
    # Docs compliance: public clients must bind authorization codes with PKCE.
    challenge = params.get("code_challenge")
    if not challenge:
        return "Missing code_challenge"
    if not CODE_CHALLENGE_PATTERN.match(challenge):
        return "Invalid code_challenge"
    method = params.get("code_challenge_method")
    if method and method not in {"S256", "plain"}:
        return "Unsupported code_challenge_method"
    return None


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
    error = _validate_authorize_params(params)
    if error:
        return _authorize_form(params, error=error)
    return _authorize_form(params)


async def authorize_post(request: Request) -> Response:
    """Issue an authorization code after form approval and redirect the client back."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items() if k != "pin"}
    error = _validate_authorize_params(params)
    if error:
        return _authorize_form(params, error=error)

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

    code = secrets.token_urlsafe(32)
    normalized_scope = normalize_requested_scope(params.get("scope"))
    auth_code = AuthCode(
        code=code,
        client_id=params["client_id"],
        redirect_uri=params["redirect_uri"],
        scope=normalized_scope,
        resource=_normalize_resource(params["resource"]),
        code_challenge=params.get("code_challenge"),
        code_challenge_method=params.get("code_challenge_method"),
    )
    _CODES[code] = auth_code
    audit(
        "oauth_code_issued",
        client_id=auth_code.client_id,
        resource=auth_code.resource,
    )
    query = {"code": code, "iss": issuer_url(request)}
    if params.get("state"):
        query["state"] = params["state"]
    return oauth_redirect(params["redirect_uri"], query)
