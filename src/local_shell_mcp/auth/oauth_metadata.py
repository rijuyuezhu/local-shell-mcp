"""OAuth protected-resource and authorization-server metadata."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .oauth_responses import _json
from .oauth_urls import (
    _scopes,
    issuer_url,
    protected_resource_metadata_url,
    public_base_url,
    resource_url,
)


def protected_resource_metadata(request: Request) -> dict[str, Any]:
    """Build RFC-style protected-resource metadata for MCP clients discovering authorization servers."""
    return {
        "resource": resource_url(request),
        "authorization_servers": [issuer_url(request)],
        "scopes_supported": _scopes(),
        "resource_documentation": f"{public_base_url(request)}/docs",
    }


def authorization_server_metadata(request: Request) -> dict[str, Any]:
    """Build OAuth authorization-server metadata for dynamic clients and PKCE code flow."""
    issuer = issuer_url(request)
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


async def oauth_protected_resource(request: Request) -> JSONResponse | Response:
    """Serve protected-resource metadata from the RFC9728 well-known URL."""
    expected_path = urlparse(protected_resource_metadata_url(request)).path
    if request.url.path != expected_path:
        return Response(status_code=404)
    return _json(protected_resource_metadata(request))


async def oauth_server_metadata(request: Request) -> JSONResponse:
    """Serve authorization-server metadata from the well-known OAuth endpoint."""
    return _json(authorization_server_metadata(request))
