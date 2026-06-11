"""Build the FastAPI application that exposes shell, filesystem, git, remote-worker, and MCP endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth.middleware import (
    CloudflareAccessMiddleware,
    Principal,
    verify_request,
)
from .config.settings import get_settings
from .ops.shell_ops import PUBLIC_RUN_SHELL_TIMEOUT_CAP_S
from .tools.local_invocations import HTTP_TOOL_ROUTES, call_local_tool

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
    for (method, path), tool_name in HTTP_TOOL_ROUTES.items():
        if method == "GET":

            async def get_handler(
                _: Principal = PRINCIPAL_DEP,
                *,
                _tool_name: str = tool_name,
            ):
                return await call_local_tool(_tool_name, {})

            app.get(path)(get_handler)
            continue

        async def post_handler(
            body: dict[str, Any] | None = None,
            _: Principal = PRINCIPAL_DEP,
            *,
            _tool_name: str = tool_name,
        ):
            return await call_local_tool(_tool_name, _tool_body(body))

        app.post(path)(post_handler)


def build_http_app() -> FastAPI:
    """Construct the authenticated HTTP API and mount MCP, OAuth, tool, and remote-worker routes."""
    app = FastAPI(title="local-shell-mcp REST API", version="0.1.0")
    settings = get_settings()
    if settings.auth_mode != "none":
        app.add_middleware(CloudflareAccessMiddleware)

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
