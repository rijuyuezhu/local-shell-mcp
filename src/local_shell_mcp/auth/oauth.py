"""OAuth compatibility facade for HTTP mode."""

from __future__ import annotations

from .oauth_authorization import (
    _authorize_form,
    _hidden_inputs,
    _make_redirect,
    _validate_authorize_params,
    oauth_authorize_get,
    oauth_authorize_post,
)
from .oauth_metadata import (
    authorization_server_metadata,
    oauth_protected_resource,
    oauth_server_metadata,
    protected_resource_metadata,
)
from .oauth_models import _CLIENTS, _CODES, AuthCode, OAuthClient
from .oauth_registration import oauth_register
from .oauth_responses import (
    _invalid_grant,
    _invalid_request,
    _json,
    _oauth_error,
)
from .oauth_tokens import (
    _jwt_secret,
    _verify_pkce,
    issue_access_token,
    oauth_token,
    validate_bearer_token,
)
from .oauth_urls import (
    _default_scope,
    _normalize_resource,
    _scopes,
    issuer_url,
    public_base_url,
    resource_url,
)

__all__ = [
    "AuthCode",
    "OAuthClient",
    "_CLIENTS",
    "_CODES",
    "_authorize_form",
    "_default_scope",
    "_hidden_inputs",
    "_invalid_grant",
    "_invalid_request",
    "_json",
    "_jwt_secret",
    "_make_redirect",
    "_normalize_resource",
    "_oauth_error",
    "_scopes",
    "_validate_authorize_params",
    "_verify_pkce",
    "authorization_server_metadata",
    "issue_access_token",
    "issuer_url",
    "oauth_authorize_get",
    "oauth_authorize_post",
    "oauth_protected_resource",
    "oauth_register",
    "oauth_server_metadata",
    "oauth_token",
    "protected_resource_metadata",
    "public_base_url",
    "resource_url",
    "validate_bearer_token",
]
