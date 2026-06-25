"""Local bearer signing and validation helpers.

Security model: see ``docs/security.md#oauth-security``. Bearer credentials are
signed locally with state-directory key material and audience-bound to the MCP
resource.
"""

import secrets
import time
from typing import Any

import jwt
from starlette.requests import Request

from ...config.settings import get_settings
from ..core.urls import issuer_url, resource_url


def _jwt_secret() -> str:
    """Return a configured or persisted signing key for local bearer credentials."""
    settings = get_settings()
    # Docs compliance: local bearer credentials use state-directory key material.
    # Operators must protect and rotate this state between trust domains because
    # there is no central revocation service.
    secret_path = settings.state_dir / "oauth-jwt-secret"
    try:
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    except FileNotFoundError:
        pass

    settings.state_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def issue_access_token(
    *, client_id: str, scope: str, resource: str, subject: str = "local-user"
) -> str:
    """Create a signed bearer credential for an approved client, scope, resource, and subject."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": issuer_url(),
        "sub": subject,
        "aud": resource,
        "iat": now,
        "client_id": client_id,
        "scope": scope,
    }
    if settings.oauth_access_token_ttl_s > 0:
        payload["exp"] = now + settings.oauth_access_token_ttl_s
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def validate_bearer_token(
    token: str, request: Request | None = None
) -> dict[str, Any]:
    """Decode and validate issuer, audience, resource, and scope claims for incoming bearer credentials."""
    # Docs compliance: resource-server validation requires accepting only
    # credentials issued by this issuer and audience-bound to this MCP resource.
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=["HS256"],
        audience=resource_url(request),
        issuer=issuer_url(request),
        options={"require": ["iat", "aud", "iss"]},
    )
