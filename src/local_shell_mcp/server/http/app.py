"""Build the FastAPI REST HTTP application."""

import uvicorn
from fastapi import FastAPI

from ... import __version__
from ...config.settings import get_settings
from ...oauth.middleware import AuthMiddleware
from ..shared.public_routes import install_public_http_routes
from .errors import install_error_handlers
from .tool_routes import (
    install_tools_timeout_middleware,
    register_http_tool_routes,
)


def build_http_app() -> FastAPI:
    """Construct the authenticated REST API and register local tool routes."""
    settings = get_settings()
    app = FastAPI(title="local-shell-mcp REST API", version=__version__)
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware)

    install_error_handlers(app)
    install_tools_timeout_middleware(app)
    install_public_http_routes(app, settings)
    register_http_tool_routes(app)
    return app


def run_http() -> None:
    """Run the REST HTTP server."""
    settings = get_settings()
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)
