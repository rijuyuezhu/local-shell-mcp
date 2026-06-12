"""Response envelope helpers shared by remote manager and HTTP endpoints."""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse


def _ok(data: Any = None, message: str = "") -> dict[str, Any]:
    """Build a consistent success envelope for remote-worker HTTP endpoints."""
    return {"ok": True, "message": message, "data": data}


def _error(
    message: str, error: str = "remote_error", status_code: int = 400
) -> JSONResponse:
    """Build a consistent error envelope with the HTTP status code mirrored in the payload."""
    return JSONResponse(
        {"ok": False, "error": error, "message": message},
        status_code=status_code,
    )
