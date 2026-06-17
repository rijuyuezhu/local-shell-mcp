"""HTTP exception handlers."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ...tools.local_invocations import UnknownLocalToolError


def install_error_handlers(app: FastAPI) -> None:
    """Install JSON exception handlers for REST API errors."""

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
            content={
                "ok": False,
                "error": "unknown_tool",
                "message": str(exc),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": "http_error",
                "message": exc.detail,
            },
            headers=exc.headers,
        )
