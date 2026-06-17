"""HTTP routes for remote worker bootstrap, polling, and results."""

import shlex
from importlib import resources

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from ..config.settings import get_settings
from .bundle import worker_bundle
from .constants import (
    REMOTE_API_PREFIX,
    REMOTE_JOIN_PATH,
    REMOTE_WORKER_BUNDLE_PATH,
)
from .manager import remote_manager
from .responses import _error, _ok

JOIN_SCRIPT_RESOURCE = "join_worker.sh"


def _bearer_token(request: Request) -> str:
    """Extract the worker bearer token from an Authorization header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


async def join_script(request: Request) -> PlainTextResponse:
    """Serve a shell script that installs and starts a remote worker for a pending invite."""
    settings = get_settings()
    server = settings.resolved_base_url
    script = (
        resources.files(__package__)
        .joinpath(JOIN_SCRIPT_RESOURCE)
        .read_text(encoding="utf-8")
        .replace("__REMOTE_SERVER__", shlex.quote(server))
        .replace("__REMOTE_WORKER_BUNDLE_PATH__", REMOTE_WORKER_BUNDLE_PATH)
    )
    return PlainTextResponse(script, media_type="text/x-shellscript")


async def register_endpoint(request: Request) -> JSONResponse:
    """Register a worker over HTTP and return its long-poll token."""
    try:
        return JSONResponse(
            _ok(await remote_manager().register_worker(await request.json()))
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 400)


async def poll_endpoint(request: Request) -> JSONResponse:
    """Long-poll for the next job assigned to the authenticated worker."""
    try:
        return JSONResponse(
            _ok(await remote_manager().poll(_bearer_token(request)))
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


async def result_endpoint(request: Request) -> JSONResponse:
    """Accept the authenticated worker's result for its current job."""
    try:
        return JSONResponse(
            _ok(
                await remote_manager().submit_result(
                    _bearer_token(request), await request.json()
                )
            )
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


def remote_routes() -> list[Route]:
    """Create the APIRouter containing worker bootstrap and control endpoints."""
    return [
        Route(REMOTE_JOIN_PATH, join_script, methods=["GET"]),
        Route(REMOTE_WORKER_BUNDLE_PATH, worker_bundle, methods=["GET"]),
        Route(
            f"{REMOTE_API_PREFIX}/register", register_endpoint, methods=["POST"]
        ),
        Route(f"{REMOTE_API_PREFIX}/poll", poll_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/result", result_endpoint, methods=["POST"]),
    ]
