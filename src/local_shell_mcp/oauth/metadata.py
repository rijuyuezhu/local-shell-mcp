"""OAuth protected-resource and authorization-server metadata.

Security model: see ``docs/security.md#oauth-security``. This module exposes the
metadata documents required for MCP clients to discover the authorization server
without guessing endpoints.
"""

from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .responses import _json
from .urls import (
    _scopes,
    issuer_url,
    protected_resource_metadata_url,
    public_base_url,
    resource_url,
)


def protected_resource_metadata(request: Request) -> dict[str, Any]:
    """Build RFC-style protected-resource metadata for MCP clients discovering authorization servers."""
    # Docs compliance: MCP requires protected-resource metadata to include the
    # canonical resource and at least one authorization server.
    return {
        "resource": resource_url(request),
        "authorization_servers": [issuer_url(request)],
        "scopes_supported": _scopes(),
        "resource_documentation": f"{public_base_url(request)}/docs",
    }


def authorization_server_metadata(request: Request) -> dict[str, Any]:
    """Build OAuth authorization-server metadata for dynamic clients and PKCE code flow."""
    issuer = issuer_url(request)
    # Docs compliance: RFC 8414 authorization-server metadata advertises the
    # endpoints and capabilities used by dynamic clients and PKCE code flow.
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": _scopes(),
        "authorization_response_iss_parameter_supported": True,
        "resource_parameter_supported": True,
    }


async def protected_resource_endpoint(
    request: Request,
) -> JSONResponse | Response:
    """Serve protected-resource metadata from the RFC9728 well-known URL."""
    # Docs compliance: path-based protected resources must only serve metadata
    # at their RFC 9728-derived well-known URL. Mismatched suffixes are rejected
    # so ``/.well-known/oauth-protected-resource/other`` cannot describe ``/mcp``.
    expected_path = urlparse(protected_resource_metadata_url(request)).path
    if request.url.path != expected_path:
        return Response(status_code=404)
    return _json(protected_resource_metadata(request))


async def server_metadata_endpoint(request: Request) -> JSONResponse:
    """Serve authorization-server metadata from the well-known OAuth endpoint."""
    return _json(authorization_server_metadata(request))
