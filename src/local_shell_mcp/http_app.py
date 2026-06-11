"""Build the FastAPI application that exposes shell, filesystem, git, remote-worker, and MCP endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth.middleware import (
    AuthMiddleware,
    Principal,
    verify_request,
)
from .config.settings import get_settings
from .ops.shell_ops import PUBLIC_RUN_SHELL_TIMEOUT_CAP_S
from .tools.discovery import discover_tool_registries
from .tools.local_invocations import call_local_tool

PUBLIC_TOOL_TIMEOUT_S = PUBLIC_RUN_SHELL_TIMEOUT_CAP_S


def principal_dep(request: Request) -> Principal:
    """Expose the principal installed by auth middleware to FastAPI route handlers."""
    return verify_request(request)


PRINCIPAL_DEP = Depends(principal_dep)


def _tool_body(body: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize absent HTTP request bodies to the empty tool argument set."""
    return body or {}


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


def _make_get_tool_handler(tool_name: str):
    async def get_handler(_: Principal = PRINCIPAL_DEP):
        return await call_local_tool(tool_name, {})

    return get_handler


def _make_post_tool_handler(tool_name: str):
    async def post_handler(
        body: dict[str, Any] | None = None,
        _: Principal = PRINCIPAL_DEP,
    ):
        return await call_local_tool(tool_name, _tool_body(body))

    return post_handler


def build_http_app() -> FastAPI:
    """Construct the authenticated HTTP API and mount MCP, OAuth, tool, and remote-worker routes."""
    app = FastAPI(title="local-shell-mcp REST API", version="0.1.0")
    settings = get_settings()
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):  # noqa: ARG001
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "validation_error",
                "message": str(exc),
            },
        )

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):  # noqa: ARG001
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "unknown_tool", "message": str(exc)},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):  # noqa: ARG001
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": "http_error", "message": exc.detail},
        )

    @app.middleware("http")
    async def tools_timeout_middleware(request: Request, call_next):  # noqa: ANN001
        if not request.url.path.startswith("/tools/"):
            return await call_next(request)
        try:
            return await asyncio.wait_for(
                call_next(request), timeout=PUBLIC_TOOL_TIMEOUT_S
            )
        except TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "ok": False,
                    "error": "tool_timeout",
                    "message": f"{request.url.path} exceeded {PUBLIC_TOOL_TIMEOUT_S} second public tool timeout",
                },
            )

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        return {"ok": True, "workspace_root": str(settings.workspace_root)}

    _register_http_tool_routes(app)
    return app


def run_http() -> None:
    """Run the HTTP server with REST tool routes and health endpoints."""
    settings = get_settings()
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)
