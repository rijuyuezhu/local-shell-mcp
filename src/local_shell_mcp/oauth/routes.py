"""Public OAuth route helpers for HTTP-capable transports.

Security model: see ``docs/security.md#oauth-security``. These routes expose
OAuth discovery and bootstrap endpoints that remain public while tool and MCP
routes are protected by AuthMiddleware.
"""

from starlette.routing import Route

from .authorization import authorize_get, authorize_post
from .metadata import protected_resource_endpoint, server_metadata_endpoint
from .registration import register_client
from .tokens import token_endpoint


def oauth_public_routes() -> list[Route]:
    """Return public OAuth discovery, registration, authorization, and token routes."""
    return [
        # Docs compliance: protected-resource metadata and AS metadata are
        # public discovery routes; AuthMiddleware protects tool/MCP routes.
        Route(
            "/.well-known/oauth-protected-resource",
            protected_resource_endpoint,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource/{resource_path:path}",
            protected_resource_endpoint,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            server_metadata_endpoint,
            methods=["GET"],
        ),
        Route(
            "/.well-known/openid-configuration",
            server_metadata_endpoint,
            methods=["GET"],
        ),
        Route("/oauth/register", register_client, methods=["POST"]),
        Route("/oauth/authorize", authorize_get, methods=["GET"]),
        Route("/oauth/authorize", authorize_post, methods=["POST"]),
        Route("/oauth/token", token_endpoint, methods=["POST"]),
    ]
