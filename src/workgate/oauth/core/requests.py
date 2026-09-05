"""Typed OAuth service input models.

These models are built by HTTP adapters before calling ``oauth.core.service`` so
core service functions receive explicit inputs instead of raw Starlette request
data or untyped dictionaries.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistrationRequest:
    """Parsed dynamic client registration request."""

    redirect_uris: tuple[str, ...]
    """Redirect URIs supplied by the dynamic client registration payload."""

    client_name: str | None = None
    """Optional client display name supplied by the dynamic registration payload."""


@dataclass(frozen=True)
class AuthorizationRequestInput:
    """Parsed authorization endpoint request parameters."""

    response_type: str | None = None
    """Requested OAuth authorization response type."""

    client_id: str | None = None
    """Dynamic client identifier supplied by the OAuth client."""

    redirect_uri: str | None = None
    """Redirect URI supplied by the OAuth client."""

    resource: str | None = None
    """RFC 8707 protected resource indicator supplied by the OAuth client."""

    scope: str | None = None
    """Optional space-delimited OAuth scope string requested by the client."""

    state: str | None = None
    """Optional opaque OAuth state returned to the client redirect URI."""

    code_challenge: str | None = None
    """PKCE code challenge supplied by the public OAuth client."""

    code_challenge_method: str | None = None
    """PKCE challenge method supplied by the public OAuth client."""

    extra_params: Mapping[str, str] = field(default_factory=dict)
    """Additional request parameters preserved for form redisplay."""

    def to_oauth_params(self) -> dict[str, str]:
        """Return OAuth parameters as a concrete mapping for protocol adapters."""
        params = dict(self.extra_params)
        known = {
            "response_type": self.response_type,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "resource": self.resource,
            "scope": self.scope,
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": self.code_challenge_method,
        }
        params.update({key: value for key, value in known.items() if value})
        return params


@dataclass(frozen=True)
class TokenRequestInput:
    """Parsed token endpoint authorization-code exchange request."""

    grant_type: str | None = None
    """OAuth grant type requested by the client."""

    code: str | None = None
    """Authorization code presented by the OAuth client."""

    client_id: str | None = None
    """Dynamic client identifier presented by the OAuth client."""

    redirect_uri: str | None = None
    """Redirect URI presented by the OAuth client for binding checks."""

    resource: str | None = None
    """RFC 8707 resource indicator presented for token audience binding."""

    code_verifier: str | None = None
    """PKCE verifier presented by the OAuth client."""

    def to_oauth_params(self) -> dict[str, str]:
        """Return OAuth parameters as a concrete mapping for protocol adapters."""
        known = {
            "grant_type": self.grant_type,
            "code": self.code,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "resource": self.resource,
            "code_verifier": self.code_verifier,
        }
        return {key: value for key, value in known.items() if value}
