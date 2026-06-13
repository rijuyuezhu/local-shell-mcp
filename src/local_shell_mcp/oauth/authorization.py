"""OAuth authorization endpoint, local approval form, and code issuance.

Security model: see ``docs/security.md#oauth-security``. Authorization requests
are validated before rendering local approval UI or issuing one-time codes.
"""

from __future__ import annotations

import hmac
import html as html_lib
import secrets
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlencode

from authlib.oauth2.rfc7636.challenge import CODE_CHALLENGE_PATTERN
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from ..audit import audit
from ..config.settings import get_settings
from .models import _CLIENTS, _CODES, AuthCode
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
    if (
        client
        and client.redirect_uris
        and params["redirect_uri"] not in client.redirect_uris
    ):
        return "redirect_uri is not registered for this client"
    # Docs compliance: accept only syntactically valid PKCE challenge material;
    # S256 is advertised and preferred, while plain remains for compatibility.
    challenge = params.get("code_challenge")
    if challenge and not CODE_CHALLENGE_PATTERN.match(challenge):
        return "Invalid code_challenge"
    method = params.get("code_challenge_method")
    if method and method not in {"S256", "plain"}:
        return "Unsupported code_challenge_method"
    return None


def _hidden_inputs(params: dict[str, str]) -> str:
    """Preserve validated authorization parameters as hidden fields in the approval form."""

    return "\n".join(
        f'<input type="hidden" name="{html_lib.escape(k, quote=True)}" value="{html_lib.escape(v, quote=True)}" />'
        for k, v in params.items()
    )


def _authorize_form(
    params: dict[str, str], error: str | None = None
) -> HTMLResponse:
    """Render the local approval form used before issuing an authorization code."""
    settings = get_settings()
    scope = params.get("scope") or _default_scope()
    resource = params.get("resource") or resource_url()
    error_html = (
        f'<p style="color:#b00020">{html_lib.escape(error)}</p>'
        if error
        else ""
    )
    pin_hint = "Enter LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN to approve this ChatGPT connector."
    if not settings.oauth_admin_pin:
        pin_hint = "No admin PIN is configured. Click Approve to continue. Set LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN before exposing this publicly."
    html = (
        _authorize_template()
        .replace("{{RESOURCE}}", html_lib.escape(resource))
        .replace("{{SCOPE}}", html_lib.escape(scope))
        .replace("{{ERROR_HTML}}", error_html)
        .replace("{{HIDDEN_INPUTS}}", _hidden_inputs(params))
        .replace("{{PIN_HINT}}", html_lib.escape(pin_hint))
    )
    return HTMLResponse(html)


def _make_redirect(
    redirect_uri: str, query: dict[str, str]
) -> RedirectResponse:
    """Append authorization response parameters to a redirect URI."""
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{sep}{urlencode(query)}", status_code=302
    )


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
    # Docs compliance: the optional admin PIN gates local user approval; use a
    # constant-time comparison so failed PIN attempts do not leak prefix timing.
    if expected_pin and not hmac.compare_digest(submitted_pin, expected_pin):
        audit("oauth_pin_failed", client_id=params.get("client_id"))
        return _authorize_form(params, error="Invalid admin PIN")

    code = secrets.token_urlsafe(32)
    auth_code = AuthCode(
        code=code,
        client_id=params["client_id"],
        redirect_uri=params["redirect_uri"],
        scope=params.get("scope") or _default_scope(),
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
    return _make_redirect(params["redirect_uri"], query)
