"""Build the FastAPI REST application that exposes local tool endpoints."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from ..config.settings import get_settings
from ..oauth.middleware import (
    AuthMiddleware,
    Principal,
    verify_request,
)
from ..ops.command_ops import public_tool_timeout_s
from ..tools.discovery import discover_tool_registries
from ..tools.local_invocations import UnknownLocalToolError, call_local_tool

type ToolRouteHandler = Callable[..., Awaitable[Any]]


def principal_dep(request: Request) -> Principal:
    """Expose the principal installed by auth middleware to FastAPI route handlers."""
    return verify_request(request)


PRINCIPAL_DEP = Depends(principal_dep)


def _register_http_tool_routes(app: FastAPI) -> None:
    """Register REST tool endpoints from the shared local tool routing table."""
    routes = [
        route
        for registry in discover_tool_registries()
        for route in registry.http_routes()
    ]
    for route in routes:
        match route.method:
            case "GET":
                app.get(route.path)(_make_get_tool_handler(route.tool_name))
            case "POST":
                app.post(route.path)(_make_post_tool_handler(route.tool_name))
            case _:
                raise ValueError(
                    f"Unsupported HTTP tool method {route.method!r} for {route.path}"
                )


def _make_get_tool_handler(tool_name: str) -> ToolRouteHandler:
    async def get_handler(principal: Principal = PRINCIPAL_DEP) -> Any:
        return await call_local_tool(
            tool_name,
            None,
            audit_context={
                "principal": principal,
                "path": f"/tools/{tool_name}",
            },
        )

    return get_handler


def _make_post_tool_handler(tool_name: str) -> ToolRouteHandler:
    async def post_handler(
        body: dict[str, Any] | None = None,
        principal: Principal = PRINCIPAL_DEP,
    ) -> Any:
        return await call_local_tool(
            tool_name,
            body,
            audit_context={
                "principal": principal,
                "path": f"/tools/{tool_name}",
            },
        )

    return post_handler


def build_http_app() -> FastAPI:
    """Construct the authenticated REST API and register local tool routes."""
    app = FastAPI(title="local-shell-mcp REST API", version="0.1.0")
    settings = get_settings()
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware)

    @app.exception_handler(ValueError)
    async def value_error_handler(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "validation_error",
                "message": str(exc),
            },
        )

    @app.exception_handler(UnknownLocalToolError)
    async def unknown_tool_handler(
        request: Request, exc: UnknownLocalToolError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "unknown_tool", "message": str(exc)},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": "http_error", "message": exc.detail},
            headers=exc.headers,
        )

    @app.middleware("http")
    async def tools_timeout_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not request.url.path.startswith("/tools/"):
            return await call_next(request)
        try:
            return await asyncio.wait_for(
                call_next(request), timeout=public_tool_timeout_s()
            )
        except TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "ok": False,
                    "error": "tool_timeout",
                    "message": f"{request.url.path} exceeded {public_tool_timeout_s()} second public tool timeout",
                },
            )

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz")
    async def readyz() -> dict[str, bool | str]:
        return {"ok": True, "workspace_root": str(settings.workspace_root)}

    _register_http_tool_routes(app)
    return app


def run_http() -> None:
    """Run the HTTP server with REST tool routes and health endpoints."""
    settings = get_settings()
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)
