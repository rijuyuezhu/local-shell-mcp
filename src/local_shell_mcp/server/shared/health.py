"""Shared health and readiness HTTP routes."""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ...config.settings import Settings
from ...version import version_info


def health_response(request: Request) -> JSONResponse:
    """Return a lightweight process health response."""
    return JSONResponse({"ok": True})


def version_response(request: Request) -> JSONResponse:
    """Return package and runtime version metadata."""
    return JSONResponse(version_info())


def make_ready_response(settings: Settings, *, include_workspace_root: bool):
    """Return a readiness endpoint bound to the active settings."""

    def ready_response(request: Request) -> JSONResponse:
        payload: dict[str, bool | str] = {"ok": True}
        if include_workspace_root:
            payload["workspace_root"] = str(settings.workspace_root)
        return JSONResponse(payload)

    return ready_response


def health_routes(
    settings: Settings, *, readyz_include_workspace_root: bool
) -> list[Route]:
    """Return public Starlette health and readiness routes."""
    return [
        Route("/healthz", health_response, methods=["GET"]),
        Route(
            "/readyz",
            make_ready_response(
                settings,
                include_workspace_root=readyz_include_workspace_root,
            ),
            methods=["GET"],
        ),
        Route("/version", version_response, methods=["GET"]),
    ]
