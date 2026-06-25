"""OAuth data models and in-memory state stores.

Security model: see ``docs/security.md#oauth-security``. Client registrations
and authorization codes are intentionally process-local; restart drops them.
"""

import time
from dataclasses import dataclass, field


@dataclass
class OAuthClient:
    """Dynamically registered OAuth client metadata used during authorization and token exchange."""

    client_id: str
    """Opaque identifier assigned to the dynamically registered client."""
    redirect_uris: list[str] = field(default_factory=list)
    """Redirect URIs accepted for authorization-code callbacks."""
    client_name: str | None = None
    """Optional human-readable client name supplied during registration."""
    created_at: int = field(default_factory=lambda: int(time.time()))
    """Unix timestamp when the client registration was created."""


@dataclass
class AuthCode:
    """Short-lived authorization code record including PKCE challenge and requested resource scope."""

    code: str
    """Opaque authorization code returned to the OAuth client."""
    client_id: str
    """Registered client identifier that requested the code."""
    redirect_uri: str
    """Redirect URI bound to this authorization code."""
    scope: str
    """Space-delimited scopes approved for the token exchange."""
    resource: str
    """Protected resource audience requested for the access token."""
    code_challenge: str | None
    """PKCE code challenge supplied during authorization."""
    code_challenge_method: str | None
    """PKCE challenge method, such as S256 or plain."""
    created_at: int = field(default_factory=lambda: int(time.time()))
    """Unix timestamp when the authorization code was issued."""
    used: bool = False
    """Whether this single-use code has already been exchanged."""


_CLIENTS: dict[str, OAuthClient] = {}
_CODES: dict[str, AuthCode] = {}
