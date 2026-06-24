"""Build the FastAPI REST HTTP application."""

import uvicorn
from fastapi import FastAPI
from starlette.routing import BaseRoute

from ... import __version__
from ...config.settings import Settings, get_settings
from ...oauth.middleware import AuthMiddleware
from ...oauth.routes import oauth_public_routes
from ..shared.public_routes import public_http_routes
from .errors import install_error_handlers
from .tool_routes import (
    install_tools_timeout_middleware,
    register_http_tool_routes,
)


def _fastapi_documentation_routes(app: FastAPI) -> list[BaseRoute]:
    """Return FastAPI-generated documentation routes that should stay public."""
    public_paths = {
        path
        for path in (
            app.docs_url,
            app.redoc_url,
            app.openapi_url,
            app.swagger_ui_oauth2_redirect_url,
        )
        if path is not None
    }
    return [
        route
        for route in app.router.routes
        if getattr(route, "path", None) in public_paths
    ]


def _install_public_routes(app: FastAPI, settings: Settings) -> list[BaseRoute]:
    """Install public non-tool routes for the REST app."""
    documentation_routes = _fastapi_documentation_routes(app)
    installed_routes = [
        *public_http_routes(settings, readyz_include_workspace_root=True),
        *oauth_public_routes(),
    ]
    app.router.routes.extend(installed_routes)
    return [*documentation_routes, *installed_routes]


def build_http_app() -> FastAPI:
    """Construct the authenticated REST API and register local tool routes."""
    settings = get_settings()
    app = FastAPI(title="local-shell-mcp REST API", version=__version__)

    install_error_handlers(app)
    install_tools_timeout_middleware(app)
    public_routes = _install_public_routes(app, settings)
    register_http_tool_routes(app)
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware, public_routes=public_routes)
    return app


def run_http() -> None:
    """Run the REST HTTP server."""
    settings = get_settings()
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)
