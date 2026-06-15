"""Shared public HTTP route assembly for REST and MCP transports."""

from starlette.applications import Starlette
from starlette.routing import BaseRoute

from ..config.settings import Settings
from .downloads import download_routes
from .health import health_routes


def public_http_routes(
    settings: Settings, *, readyz_include_workspace_root: bool
) -> list[BaseRoute]:
    """Return public non-OAuth routes shared by REST and MCP HTTP apps."""
    return [
        *health_routes(
            settings,
            readyz_include_workspace_root=readyz_include_workspace_root,
        ),
        *download_routes(),
    ]


def install_public_http_routes(app: Starlette, settings: Settings) -> None:
    """Install shared public routes on the REST app."""
    app.router.routes.extend(
        public_http_routes(settings, readyz_include_workspace_root=True)
    )
