"""Authenticated Human UI terminal APIs and tmux WebSocket bridge."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
import re
import threading
from typing import Any

import jwt
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket, WebSocketDisconnect

from ...audit import audit
from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import (
    SCOPE_SHELL_EXECUTE,
    SCOPE_SHELL_READ,
    scope_set,
)
from ...oauth.protocol.token_codec import validate_bearer_token
from ...ops.shell import (
    PERSISTENT_SHELL_MAX_COLUMNS,
    PERSISTENT_SHELL_MAX_ROWS,
    PERSISTENT_SHELL_MIN_COLUMNS,
    PERSISTENT_SHELL_MIN_ROWS,
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    resize_persistent_shell_execute,
    send_persistent_shell_input_execute,
    start_persistent_shell_execute,
)

UI_TERMINAL_SUBPROTOCOL = "lsm-ui-terminal"
UI_TERMINAL_INPUT_MAX_BYTES = 65_536
UI_TERMINAL_READ_MAX_LINES = 5_000
UI_TERMINAL_DEFAULT_LINES = 1_000
UI_TERMINAL_POLL_INTERVAL_S = 0.25
_SHELL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CONNECTION_IDS = itertools.count(1)
_ACTIVE_CONNECTIONS: set[int] = set()
_ACTIVE_CONNECTIONS_LOCK = threading.Lock()


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _json_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        },
        status_code=status_code,
    )


def _require_scopes(*required: str) -> None:
    try:
        require_oauth_scopes(tuple(required))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _bounded_int(
    raw: str | int | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _shell_id(value: Any) -> str:
    shell_id = str(value or "")
    if not _SHELL_ID_PATTERN.fullmatch(shell_id):
        raise ValueError(
            "shell_id must be 1-64 characters using letters, digits, '.', '_' or '-'"
        )
    return shell_id


def _websocket_protocols(websocket: WebSocket) -> list[str]:
    raw = websocket.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _websocket_token(websocket: WebSocket) -> str | None:
    for protocol in _websocket_protocols(websocket):
        if not protocol.startswith("bearer."):
            continue
        encoded = protocol.removeprefix("bearer.")
        if not encoded or len(encoded) > 16_384:
            return None
        padding = "=" * (-len(encoded) % 4)
        try:
            token = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except ValueError, UnicodeDecodeError:
            return None
        return token if token else None
    return None


def _authorize_websocket(websocket: WebSocket) -> tuple[bool, int, str]:
    """Authorize a browser WebSocket without trusting localhost proxy hops."""
    if get_settings().auth_mode == "none":
        return True, 1000, ""
    token = _websocket_token(websocket)
    if not token:
        return False, 4401, "OAuth authentication required"
    try:
        claims = validate_bearer_token(token)
    except jwt.PyJWTError:
        return False, 4401, "Invalid OAuth bearer token"
    granted = scope_set(str(claims.get("scope") or ""))
    for required in (SCOPE_SHELL_READ, SCOPE_SHELL_EXECUTE):
        if required not in granted:
            return False, 4403, f"Missing required OAuth scope: {required}"
    return True, 1000, ""


def _reserve_connection() -> int | None:
    maximum = get_settings().ui_terminal_max_connections
    with _ACTIVE_CONNECTIONS_LOCK:
        if len(_ACTIVE_CONNECTIONS) >= maximum:
            return None
        marker = next(_CONNECTION_IDS)
        _ACTIVE_CONNECTIONS.add(marker)
    return marker


def _release_connection(marker: int) -> None:
    with _ACTIVE_CONNECTIONS_LOCK:
        _ACTIVE_CONNECTIONS.discard(marker)


async def api_terminals(request: Request) -> Response:  # noqa: ARG001
    """List tmux-backed persistent shells available to the Human UI."""
    _require_scopes(SCOPE_SHELL_READ)
    result = await list_persistent_shells_execute()
    return _json_ok(result.model_dump(mode="json"))


async def api_terminal_read(request: Request) -> Response:
    """Return a bounded recent snapshot from one persistent shell."""
    _require_scopes(SCOPE_SHELL_READ)
    try:
        shell_id = _shell_id(request.query_params.get("shell_id"))
        lines = _bounded_int(
            request.query_params.get("lines"),
            default=UI_TERMINAL_DEFAULT_LINES,
            minimum=1,
            maximum=UI_TERMINAL_READ_MAX_LINES,
            label="lines",
        )
        result = await read_persistent_shell_output_execute(shell_id, lines)
        return _json_ok(result.model_dump(mode="json"))
    except Exception as exc:
        return _json_error(exc)


async def api_terminal_action(request: Request) -> Response:
    """Start, write, resize, or terminate a persistent Human UI shell."""
    _require_scopes(SCOPE_SHELL_READ, SCOPE_SHELL_EXECUTE)
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        if action == "start":
            result = await start_persistent_shell_execute(
                cwd=str(body.get("cwd") or "."),
                name=str(body["name"])
                if body.get("name") is not None
                else None,
                command=(
                    str(body["command"])
                    if body.get("command") is not None
                    else None
                ),
            )
        elif action == "send":
            shell_id = _shell_id(body.get("shell_id"))
            input_text = str(body.get("input_text") or "")
            if len(input_text.encode("utf-8")) > UI_TERMINAL_INPUT_MAX_BYTES:
                raise ValueError(
                    f"input_text exceeds {UI_TERMINAL_INPUT_MAX_BYTES} encoded bytes"
                )
            result = await send_persistent_shell_input_execute(
                shell_id,
                input_text,
                bool(body.get("enter", True)),
            )
        elif action == "resize":
            shell_id = _shell_id(body.get("shell_id"))
            cols = _bounded_int(
                body.get("cols"),
                default=120,
                minimum=PERSISTENT_SHELL_MIN_COLUMNS,
                maximum=PERSISTENT_SHELL_MAX_COLUMNS,
                label="cols",
            )
            rows = _bounded_int(
                body.get("rows"),
                default=36,
                minimum=PERSISTENT_SHELL_MIN_ROWS,
                maximum=PERSISTENT_SHELL_MAX_ROWS,
                label="rows",
            )
            result = await resize_persistent_shell_execute(shell_id, cols, rows)
        elif action == "kill":
            result = await kill_persistent_shell_execute(
                _shell_id(body.get("shell_id"))
            )
        else:
            raise ValueError(f"Unsupported terminal action: {action}")
        return _json_ok(result.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as exc:
        return _json_error(exc)


async def ui_terminal_websocket(websocket: WebSocket) -> None:
    """Stream tmux snapshots and ordered terminal controls over an authenticated socket."""
    authorized, close_code, reason = _authorize_websocket(websocket)
    if not authorized:
        await websocket.close(code=close_code, reason=reason[:120])
        return
    try:
        shell_id = _shell_id(websocket.path_params.get("shell_id"))
        lines = _bounded_int(
            websocket.query_params.get("lines"),
            default=UI_TERMINAL_DEFAULT_LINES,
            minimum=1,
            maximum=UI_TERMINAL_READ_MAX_LINES,
            label="lines",
        )
    except ValueError as exc:
        await websocket.close(code=4400, reason=str(exc)[:120])
        return

    try:
        shells = await list_persistent_shells_execute()
    except Exception:
        await websocket.close(
            code=1011, reason="Unable to inspect persistent shells"
        )
        return
    if shell_id not in {item.shell_id for item in shells.shells}:
        await websocket.close(code=4404, reason="Persistent shell not found")
        return

    marker = _reserve_connection()
    if marker is None:
        await websocket.close(
            code=4429, reason="Too many Human UI terminal connections"
        )
        return

    protocols = _websocket_protocols(websocket)
    subprotocol = (
        UI_TERMINAL_SUBPROTOCOL
        if UI_TERMINAL_SUBPROTOCOL in protocols
        else None
    )
    try:
        await websocket.accept(subprotocol=subprotocol)
    except Exception:
        _release_connection(marker)
        raise

    send_lock = asyncio.Lock()
    settings = get_settings()
    audit("ui_terminal_connected", shell_id=shell_id)

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def sender() -> None:
        previous: str | None = None
        while True:
            try:
                result = await read_persistent_shell_output_execute(
                    shell_id, lines
                )
            except Exception as exc:
                await send_json(
                    {
                        "type": "exit",
                        "shell_id": shell_id,
                        "message": str(exc),
                    }
                )
                return
            if result.output != previous:
                previous = result.output
                await send_json(
                    {
                        "type": "snapshot",
                        "shell_id": shell_id,
                        "output": result.output,
                    }
                )
            await asyncio.sleep(UI_TERMINAL_POLL_INTERVAL_S)

    async def receiver() -> None:
        idle_timeout = max(0, settings.ui_terminal_idle_timeout_s)
        while True:
            try:
                if idle_timeout:
                    message = await asyncio.wait_for(
                        websocket.receive(), timeout=idle_timeout
                    )
                else:
                    message = await websocket.receive()
            except TimeoutError:
                await websocket.close(
                    code=4408, reason="Terminal connection idle timeout"
                )
                return
            if message["type"] == "websocket.disconnect":
                return

            if message.get("bytes") is not None:
                raw = bytes(message["bytes"])
                if len(raw) > UI_TERMINAL_INPUT_MAX_BYTES:
                    await websocket.close(
                        code=4400, reason="Terminal input is too large"
                    )
                    return
                await send_persistent_shell_input_execute(
                    shell_id, raw.decode("utf-8", errors="replace"), False
                )
                continue

            text = message.get("text")
            if not text:
                continue
            if len(text.encode("utf-8")) > UI_TERMINAL_INPUT_MAX_BYTES:
                await websocket.close(
                    code=4400, reason="Terminal message is too large"
                )
                return
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                await websocket.close(
                    code=4400, reason="Terminal controls must be JSON"
                )
                return
            if not isinstance(control, dict):
                await websocket.close(
                    code=4400, reason="Terminal control must be an object"
                )
                return

            kind = control.get("type")
            if kind == "input":
                input_text = str(control.get("data") or "")
                if (
                    len(input_text.encode("utf-8"))
                    > UI_TERMINAL_INPUT_MAX_BYTES
                ):
                    await websocket.close(
                        code=4400, reason="Terminal input is too large"
                    )
                    return
                await send_persistent_shell_input_execute(
                    shell_id,
                    input_text,
                    bool(control.get("enter", False)),
                )
            elif kind == "resize":
                try:
                    cols = _bounded_int(
                        control.get("cols"),
                        default=120,
                        minimum=PERSISTENT_SHELL_MIN_COLUMNS,
                        maximum=PERSISTENT_SHELL_MAX_COLUMNS,
                        label="cols",
                    )
                    rows = _bounded_int(
                        control.get("rows"),
                        default=36,
                        minimum=PERSISTENT_SHELL_MIN_ROWS,
                        maximum=PERSISTENT_SHELL_MAX_ROWS,
                        label="rows",
                    )
                except ValueError as exc:
                    await websocket.close(code=4400, reason=str(exc)[:120])
                    return
                await resize_persistent_shell_execute(shell_id, cols, rows)
            elif kind == "ping":
                await send_json({"type": "pong", "shell_id": shell_id})
            elif kind == "close":
                return
            else:
                await websocket.close(
                    code=4400, reason="Unsupported terminal control"
                )
                return

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                task.result()
    except WebSocketDisconnect:
        pass
    finally:
        _release_connection(marker)
        audit("ui_terminal_disconnected", shell_id=shell_id)
        with contextlib.suppress(Exception):
            await websocket.close()
