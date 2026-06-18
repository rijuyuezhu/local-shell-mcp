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
                "error": "validation_error",
                "message": str(exc),
            },
        )

    @app.exception_handler(OSError)
    async def os_error_handler(request: Request, exc: OSError) -> JSONResponse:
        exc_type = type(exc).__name__
        return JSONResponse(
            status_code=400,
            content={
                "error": exc_type,
                "message": f"{exc_type}: {exc}",
            },
        )

    @app.exception_handler(UnknownLocalToolError)
    async def unknown_tool_handler(
        request: Request, exc: UnknownLocalToolError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
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
                "error": "http_error",
                "message": exc.detail,
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": f"Unhandled {type(exc).__name__}: {exc}",
            },
        )
