"""Authlib adapter types for local OAuth state."""

from collections.abc import Collection

from authlib.oauth2.rfc6749 import ClientMixin

from ..core.models import OAuthClient
from ..core.scopes import normalize_requested_scope


class LocalOAuthClient(ClientMixin):
    """Authlib ClientMixin wrapper around a dynamic local OAuth client."""

    def __init__(self, client: OAuthClient):
        self.client = client

    def get_client_id(self) -> str:
        """Return the client identifier."""
        return self.client.client_id

    def get_default_redirect_uri(self) -> str:
        """Return the first registered redirect URI."""
        return self.client.redirect_uris[0]

    def get_allowed_scope(self, scope: Collection[str] | str | None) -> str:
        """Return the normalized scope grant."""
        if scope is None or isinstance(scope, str):
            return normalize_requested_scope(scope)
        return normalize_requested_scope(" ".join(scope))

    def check_redirect_uri(self, redirect_uri: str) -> bool:
        """Return whether the redirect URI is registered."""
        return redirect_uri in self.client.redirect_uris

    def check_client_secret(self, client_secret: str) -> bool:
        """Reject client secrets for public clients."""
        del client_secret
        return False

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:
        """Return whether the endpoint auth method is supported."""
        return endpoint == "token" and method == "none"

    def check_response_type(self, response_type: str) -> bool:
        """Return whether the response type is supported."""
        return response_type == "code"

    def check_grant_type(self, grant_type: str) -> bool:
        """Return whether the grant type is supported."""
        return grant_type == "authorization_code"
