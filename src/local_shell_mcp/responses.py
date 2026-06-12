"""Small shared response envelope builders."""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse


def ok_envelope(data: Any = None, message: str = "") -> dict[str, Any]:
    """Build the common success envelope used by tool and remote responses."""
    return {"ok": True, "message": message, "data": data}


def error_envelope(message: str, error: str = "error") -> dict[str, Any]:
    """Build the common failure envelope used by HTTP endpoint responses."""
    return {"ok": False, "error": error, "message": message}


def json_error_response(
    message: str, error: str = "error", status_code: int = 400
) -> JSONResponse:
    """Build a JSONResponse from the common failure envelope."""
    return JSONResponse(
        error_envelope(message, error),
        status_code=status_code,
    )
