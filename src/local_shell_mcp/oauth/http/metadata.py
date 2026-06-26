"""OAuth protected-resource and authorization-server metadata."""

from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..core.scopes import supported_scopes
from ..core.urls import (
    base_url,
    issuer_url,
    protected_resource_metadata_url,
    resource_url,
)
from .responses import oauth_json


def protected_resource_metadata() -> dict[str, Any]:
    """Build RFC-style protected-resource metadata for MCP clients discovering authorization servers."""
    return {
        "resource": resource_url(),
        "authorization_servers": [issuer_url()],
        "scopes_supported": supported_scopes(),
        "resource_documentation": f"{base_url()}/docs",
    }


def authorization_server_metadata() -> dict[str, Any]:
    """Build OAuth authorization-server metadata for dynamic clients and PKCE code flow."""
    issuer = issuer_url()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": supported_scopes(),
        "authorization_response_iss_parameter_supported": True,
        "resource_parameter_supported": True,
    }


async def protected_resource_endpoint(
    request: Request,
) -> JSONResponse | Response:
    """Serve protected-resource metadata from the RFC9728 well-known URL."""
    expected_path = urlparse(protected_resource_metadata_url()).path
    if request.url.path != expected_path:
        return Response(status_code=404)
    return oauth_json(protected_resource_metadata())


async def server_metadata_endpoint(request: Request) -> JSONResponse:
    """Serve authorization-server metadata from the well-known OAuth endpoint."""
    return oauth_json(authorization_server_metadata())
