"""Shared public HTTP route assembly for REST and MCP transports."""

from starlette.routing import Route

from ...config.settings import Settings
from .downloads import download_routes
from .health import health_routes


def public_http_routes(
    settings: Settings, *, readyz_include_workspace_root: bool
) -> list[Route]:
    """Return public non-OAuth routes shared by REST and MCP HTTP apps."""
    return [
        *health_routes(
            settings,
            readyz_include_workspace_root=readyz_include_workspace_root,
        ),
        *download_routes(),
    ]
