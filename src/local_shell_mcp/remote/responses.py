"""Response envelope helpers shared by remote manager and HTTP endpoints."""

from typing import Any

from starlette.responses import JSONResponse

from ..responses import json_error_response, ok_envelope


def _ok(data: Any = None, message: str = "") -> dict[str, Any]:
    """Build a consistent success envelope for remote-worker HTTP endpoints."""
    return ok_envelope(data, message)


def _error(
    message: str, error: str = "remote_error", status_code: int = 400
) -> JSONResponse:
    """Build a consistent error envelope with the HTTP status code mirrored in the payload."""
    return json_error_response(message, error, status_code)
