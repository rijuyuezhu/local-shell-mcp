"""ASGI route assembly for OAuth-protected HTTP mode.

Security model: see ``docs/security.md#oauth-security``. Route ordering keeps
OAuth discovery/public bootstrap ahead of the mounted protected MCP app.
"""

from collections.abc import Sequence
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount, Route

from .authorization import authorize_get, authorize_post
from .metadata import protected_resource_endpoint, server_metadata_endpoint
from .registration import register_client
from .tokens import token_endpoint


def wrap_http_app(
    inner_app: Starlette, *, extra_routes: Sequence[BaseRoute] = ()
) -> Starlette:
    """Wrap an inner ASGI app with health, OAuth, optional extra, and fallback routes."""

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with inner_app.router.lifespan_context(inner_app):
            yield

    routes = [
        Route(
            "/healthz",
            lambda request: JSONResponse({"ok": True}),
            methods=["GET"],
        ),
        Route(
            "/readyz",
            lambda request: JSONResponse({"ok": True}),
            methods=["GET"],
        ),
        *extra_routes,
        # Docs compliance: protected-resource metadata and AS metadata are
        # public discovery routes; AuthMiddleware protects the mounted app.
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
        Mount("/", app=inner_app),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
