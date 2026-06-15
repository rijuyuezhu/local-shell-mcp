"""Public HTTP routes for tokenized file downloads."""

import mimetypes
from pathlib import Path
from typing import Any, cast

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from ...audit import audit
from ...ops.download_ops import DOWNLOAD_PREFIX, claim_download


def download_error_response(payload: dict[str, Any]) -> JSONResponse:
    """Convert an operation-level download error payload into JSONResponse."""
    status_code = int(payload.get("status_code", 500))
    return JSONResponse(
        {
            "ok": False,
            "error": str(payload.get("error", "download_error")),
            "message": str(payload.get("message", "Download failed")),
        },
        status_code=status_code,
    )


async def download_endpoint(request: Request) -> Response:
    """Serve a tokenized file download without requiring bearer auth."""
    token = request.path_params.get("token", "")
    claimed = claim_download(token, consume=request.method.upper() == "GET")
    if isinstance(claimed, dict):
        return download_error_response(claimed)

    path, link = cast(tuple[Path, dict[str, Any]], claimed)
    filename = str(link.get("filename") or path.name)
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    audit(
        "download_link_served",
        path=link.get("display_path"),
        token=token,
        method=request.method,
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "private, no-store"},
    )


def download_routes() -> list[Route]:
    """Return public Starlette routes for generated download links."""
    return [
        Route(
            f"{DOWNLOAD_PREFIX}/{{token}}",
            download_endpoint,
            methods=["GET", "HEAD"],
        )
    ]
