"""Authlib adapter types for local OAuth state.

Security model: see ``docs/security.md#oauth-security``. These adapters expose
project-owned client state to Authlib without changing the local approval model.
"""

from collections.abc import Collection, Mapping

from authlib.oauth2.rfc6749 import ClientMixin, OAuth2Request

from ..core.models import OAuthClient
from ..core.scopes import normalize_requested_scope

_AUTHLIB_ADAPTER_BASE_URI = "https://local-shell-mcp.invalid/oauth"


class LocalOAuth2Request(OAuth2Request):
    """Small Authlib request wrapper for Starlette query/form parameters."""

    def __init__(self, method: str, endpoint: str, params: Mapping[str, str]):
        # Authlib validates transport security in OAuth2Request.__init__. Use a
        # synthetic HTTPS URI because canonical issuer/resource handling is
        # project-owned and intentionally ignores inbound Host headers.
        super().__init__(method, f"{_AUTHLIB_ADAPTER_BASE_URI}/{endpoint}")
        self.params = dict(params)

    @property
    def args(self) -> dict[str, str | None]:
        """Return query-style OAuth parameters for Authlib validators."""
        return dict(self.params)

    @property
    def form(self) -> dict[str, str]:
        """Return form-style OAuth parameters for Authlib validators."""
        return dict(self.params)


class LocalOAuthClient(ClientMixin):
    """Authlib ClientMixin wrapper around a dynamic local OAuth client."""

    def __init__(self, client: OAuthClient):
        self.client = client

    def get_client_id(self) -> str:
        """Return the dynamic client identifier."""
        return self.client.client_id

    def get_default_redirect_uri(self) -> str:
        """Return the first registered redirect URI."""
        return self.client.redirect_uris[0]

    def get_allowed_scope(self, scope: Collection[str] | str | None) -> str:
        """Return normalized supported scopes for this local client."""
        if scope is None or isinstance(scope, str):
            return normalize_requested_scope(scope)
        return normalize_requested_scope(" ".join(scope))

    def check_redirect_uri(self, redirect_uri: str) -> bool:
        """Return whether the redirect URI was registered by the client."""
        return redirect_uri in self.client.redirect_uris

    def check_client_secret(self, client_secret: str) -> bool:
        """Reject client secrets because dynamic clients are public clients."""
        del client_secret
        return False

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:
        """Support public-client token endpoint authentication only."""
        return endpoint == "token" and method == "none"

    def check_response_type(self, response_type: str) -> bool:
        """Support the authorization-code response type only."""
        return response_type == "code"

    def check_grant_type(self, grant_type: str) -> bool:
        """Support the authorization-code grant type only."""
        return grant_type == "authorization_code"
