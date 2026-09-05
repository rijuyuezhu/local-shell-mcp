"""Public OAuth route helpers for HTTP-capable transports."""

from starlette.routing import Route

from .authorization import authorize_get, authorize_post
from .metadata import protected_resource_endpoint, server_metadata_endpoint
from .registration import register_client
from .tokens import token_endpoint


def oauth_public_routes() -> list[Route]:
    """Return public OAuth discovery, registration, authorization, and token routes."""
    return [
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
