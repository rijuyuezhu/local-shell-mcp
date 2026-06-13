"""ASGI route assembly for OAuth-protected HTTP mode."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount, Route

from .oauth_authorization import oauth_authorize_get, oauth_authorize_post
from .oauth_metadata import oauth_protected_resource, oauth_server_metadata
from .oauth_registration import oauth_register
from .oauth_tokens import oauth_token


def wrap_with_oauth_routes(
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
        Route(
            "/.well-known/oauth-protected-resource",
            oauth_protected_resource,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource/{resource_path:path}",
            oauth_protected_resource,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            oauth_server_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/openid-configuration",
            oauth_server_metadata,
            methods=["GET"],
        ),
        Route("/oauth/register", oauth_register, methods=["POST"]),
        Route("/oauth/authorize", oauth_authorize_get, methods=["GET"]),
        Route("/oauth/authorize", oauth_authorize_post, methods=["POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Mount("/", app=inner_app),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
