"""REST routes and middleware for local tool invocations."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from ...oauth.middleware import Principal, verify_request
from ...ops.command_ops import public_tool_timeout_s
from ...tools.discovery import discover_tool_registries
from ...tools.local_invocations import call_local_tool

type ToolRouteHandler = Callable[..., Awaitable[Any]]


def principal_dep(request: Request) -> Principal:
    """Expose the principal installed by auth middleware to FastAPI route handlers."""
    return verify_request(request)


PRINCIPAL_DEP = Depends(principal_dep)


def install_tools_timeout_middleware(app: FastAPI) -> None:
    """Install the public timeout middleware for REST tool routes."""

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


def register_http_tool_routes(app: FastAPI) -> None:
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
