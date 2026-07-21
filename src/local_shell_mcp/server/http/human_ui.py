"""Fork-native Human UI routes shared by browser and future OpenTUI clients."""

from __future__ import annotations

import html
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any

from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
)
from starlette.routing import BaseRoute, Route, WebSocketRoute

from ...config.settings import Settings, get_settings
from ...oauth.core.scopes import default_scope
from ...oauth.core.urls import issuer_url, resource_url
from ...remote.manager import remote_manager
from ...ui_security import UI_API_PREFIX
from ...version import version_info
from .ui_audit import api_audit, api_audit_detail
from .ui_dashboard import api_dashboard
from .ui_files import (
    api_file_action,
    api_file_content,
    api_file_preview,
    api_files,
)
from .ui_remotes import api_remote_action, api_remotes
from .ui_terminals import (
    api_terminal_action,
    api_terminal_read,
    api_terminals,
    ui_terminal_websocket,
)
from .ui_todos import api_todos


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    """Return the stable Human UI success envelope."""
    return JSONResponse({"ok": True, "message": message, "data": data})


def _assets_dir() -> Path:
    """Return the packaged browser asset directory."""
    return Path(__file__).resolve().parents[2] / "ui_static"


def _ui_index_html(settings: Settings) -> str:
    """Load the browser shell and inject non-sensitive runtime configuration."""
    path = _assets_dir() / "index.html"
    if not path.is_file():
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>local-shell-mcp Human UI</title></head>"
            "<body><h1>Human UI assets are not installed</h1></body></html>"
        )
    oauth = None
    if settings.auth_mode == "oauth":
        oauth = {
            "issuer": issuer_url(),
            "resource": resource_url(),
            "scope": default_scope(),
            "registrationEndpoint": "/oauth/register",
            "authorizationEndpoint": "/oauth/authorize",
            "tokenEndpoint": "/oauth/token",
        }
    config = html.escape(
        json.dumps(
            {
                "uiPath": settings.ui_path,
                "apiPrefix": UI_API_PREFIX,
                "authMode": settings.auth_mode,
                "oauth": oauth,
            },
            separators=(",", ":"),
        ),
        quote=True,
    )
    return (
        path.read_text(encoding="utf-8")
        .replace("__LSM_UI_PATH__", settings.ui_path)
        .replace("__LSM_UI_CONFIG_JSON__", config)
    )


def _index_headers() -> dict[str, str]:
    """Return restrictive headers for the public browser shell."""
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


async def ui_index(request: Request) -> Response:  # noqa: ARG001
    """Serve the public browser shell; API calls remain authenticated."""
    settings = get_settings()
    return HTMLResponse(_ui_index_html(settings), headers=_index_headers())


async def ui_asset(request: Request) -> Response:
    """Serve one packaged browser asset without allowing path traversal."""
    raw = request.path_params.get("path", "")
    relative = PurePosixPath(str(raw))
    if relative.is_absolute() or ".." in relative.parts:
        return Response("Not found", status_code=404)

    assets = _assets_dir().resolve()
    path = assets.joinpath(*relative.parts)
    try:
        path.resolve().relative_to(assets)
    except OSError, ValueError:
        return Response("Not found", status_code=404)
    if not path.is_file():
        return Response("Not found", status_code=404)
    return FileResponse(
        path,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _machine_rows(settings: Settings) -> dict[str, Any]:
    """Return one normalized local/remote machine inventory for UI clients."""
    rows: list[dict[str, Any]] = [
        {
            "name": "local",
            "status": "online",
            "workdir": str(settings.workspace_root),
            "last_seen": time.time(),
            "last_seen_age_s": 0.0,
            "queue_depth": 0,
            "capabilities": ["dashboard", "local", "terminals"],
            "info": {
                "target": "local",
                "version": version_info().get("version"),
            },
        }
    ]
    if settings.remote_enabled:
        remote = remote_manager().list_machines().model_dump(mode="json")
        rows.extend(remote["machines"])
    online = sum(row.get("status") == "online" for row in rows)
    offline = len(rows) - online
    return {
        "machines": rows,
        "counts": {"online": online, "offline": offline, "total": len(rows)},
    }


async def api_bootstrap(request: Request) -> Response:  # noqa: ARG001
    """Return initial authenticated state for browser and native UI clients."""
    settings = get_settings()
    return _json_ok(
        {
            "version": version_info(),
            "ui": {
                "path": settings.ui_path,
                "api_prefix": UI_API_PREFIX,
                "auth_mode": settings.auth_mode,
                "features": {
                    "dashboard": True,
                    "remote_dashboard": True,
                    "machines": True,
                    "remotes": True,
                    "terminals": True,
                    "remote_terminals": True,
                    "terminal_websocket": True,
                    "files": True,
                    "file_preview": True,
                    "file_editor": True,
                    "file_copy": True,
                    "file_move": True,
                    "file_rename": True,
                    "remote_files": True,
                    "remote_file_editor": True,
                    "todos": True,
                    "remote_todos": True,
                    "audit": True,
                    "remote_audit": True,
                },
            },
            **_machine_rows(settings),
        }
    )


async def api_machines(request: Request) -> Response:  # noqa: ARG001
    """Return the current local and remote machine inventory."""
    return _json_ok(_machine_rows(get_settings()))


def human_ui_routes(
    settings: Settings,
) -> tuple[list[BaseRoute], list[BaseRoute]]:
    """Return all Human UI routes and the subset that must remain public."""
    if not settings.ui_enabled:
        return [], []
    ui_path = settings.ui_path
    public_routes: list[BaseRoute] = [
        Route(ui_path, ui_index, methods=["GET"]),
        Route(ui_path + "/", ui_index, methods=["GET"]),
        Route(ui_path + "/callback", ui_index, methods=["GET"]),
        Route(ui_path + "/assets/{path:path}", ui_asset, methods=["GET"]),
    ]
    protected_routes: list[BaseRoute] = [
        WebSocketRoute(
            ui_path + "/ws/terminals/{shell_id}", ui_terminal_websocket
        ),
        Route(UI_API_PREFIX + "/bootstrap", api_bootstrap, methods=["GET"]),
        Route(UI_API_PREFIX + "/dashboard", api_dashboard, methods=["GET"]),
        Route(UI_API_PREFIX + "/machines", api_machines, methods=["GET"]),
        Route(UI_API_PREFIX + "/remotes", api_remotes, methods=["GET", "POST"]),
        Route(
            UI_API_PREFIX + "/remotes/{action}",
            api_remote_action,
            methods=["POST"],
        ),
        Route(UI_API_PREFIX + "/files", api_files, methods=["GET"]),
        Route(
            UI_API_PREFIX + "/files/preview",
            api_file_preview,
            methods=["GET"],
        ),
        Route(
            UI_API_PREFIX + "/files/content",
            api_file_content,
            methods=["GET"],
        ),
        Route(
            UI_API_PREFIX + "/files/{action}",
            api_file_action,
            methods=["POST"],
        ),
        Route(UI_API_PREFIX + "/todos", api_todos, methods=["GET", "PUT"]),
        Route(UI_API_PREFIX + "/audit", api_audit, methods=["GET"]),
        Route(
            UI_API_PREFIX + "/audit/detail",
            api_audit_detail,
            methods=["GET"],
        ),
        Route(UI_API_PREFIX + "/terminals", api_terminals, methods=["GET"]),
        Route(
            UI_API_PREFIX + "/terminals/read",
            api_terminal_read,
            methods=["GET"],
        ),
        Route(
            UI_API_PREFIX + "/terminals/{action}",
            api_terminal_action,
            methods=["POST"],
        ),
    ]
    return [*public_routes, *protected_routes], public_routes
