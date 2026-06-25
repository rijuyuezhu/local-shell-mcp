"""Authlib-backed bearer validation for protected resource requests.

Security model: see ``docs/security.md#oauth-security``. This module adapts
local signed bearer credentials to Authlib resource-server validators while
leaving MCP-specific challenge headers in middleware.
"""

from dataclasses import dataclass
from typing import Any

import jwt
from authlib.oauth2.rfc6749.resource_protector import ResourceProtector
from authlib.oauth2.rfc6750 import BearerTokenValidator
from starlette.requests import Request

from .token_codec import validate_bearer_token


@dataclass(frozen=True)
class LocalBearerToken:
    """Authlib token object backed by decoded local bearer claims."""

    claims: dict[str, Any]

    def get_scope(self) -> str:
        """Return the scope claim in Authlib's expected format."""
        return str(self.claims.get("scope") or "")

    def is_expired(self) -> bool:
        """Return whether the token is expired.

        PyJWT already enforces `exp` during decode when present, so a decoded
        local token is not expired at this boundary.
        """
        return False

    def is_revoked(self) -> bool:
        """Return whether the token is revoked.

        local-shell-mcp has no central token revocation store today.
        """
        return False


class LocalBearerTokenValidator(BearerTokenValidator):
    """Authlib BearerTokenValidator for locally signed bearer credentials."""

    def __init__(self, request: Request):
        super().__init__()
        self._request = request

    def authenticate_token(self, token_string: str) -> LocalBearerToken | None:
        """Decode the local bearer credential and expose claims to Authlib."""
        try:
            return LocalBearerToken(
                validate_bearer_token(token_string, self._request)
            )
        except jwt.PyJWTError:
            return None


def validate_bearer_request(request: Request) -> dict[str, Any]:
    """Validate a Starlette request with Authlib resource-server helpers."""
    protector = ResourceProtector()
    protector.register_token_validator(LocalBearerTokenValidator(request))
    token = protector.validate_request((), request)
    return token.claims
