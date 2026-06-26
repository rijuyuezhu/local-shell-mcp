"""Bearer-token validation adapters."""

from dataclasses import dataclass
from typing import Any

import jwt
from authlib.oauth2.rfc6749.resource_protector import ResourceProtector
from authlib.oauth2.rfc6750 import BearerTokenValidator

from .token_codec import validate_bearer_token


@dataclass(frozen=True)
class LocalBearerToken:
    """Decoded bearer claims exposed through Authlib's token interface."""

    claims: dict[str, Any]
    """Decoded token claims."""

    def get_scope(self) -> str:
        """Return the space-delimited scope claim."""
        return str(self.claims.get("scope") or "")

    def is_expired(self) -> bool:
        """Return whether the token is expired."""
        return False

    def is_revoked(self) -> bool:
        """Return whether the token is revoked."""
        return False


class LocalBearerTokenValidator(BearerTokenValidator):
    """BearerTokenValidator for locally signed tokens."""

    def authenticate_token(self, token_string: str) -> LocalBearerToken | None:
        """Return decoded claims for a valid token."""
        try:
            return LocalBearerToken(validate_bearer_token(token_string))
        except jwt.PyJWTError:
            return None


def bearer_resource_protector() -> ResourceProtector:
    """Return an Authlib resource protector for local bearer tokens."""
    protector = ResourceProtector()
    protector.register_token_validator(LocalBearerTokenValidator())
    return protector
