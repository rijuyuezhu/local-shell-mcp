"""Authenticated machine-aware Human UI terminal APIs and tmux bridge."""

import base64
import contextlib
from typing import Any

import jwt
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket

from ...audit import audit
from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import (
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_EXECUTE,
    SCOPE_SHELL_READ,
    scope_set,
)
from ...oauth.protocol.token_codec import validate_bearer_token
from ...ops.shell import (
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    resize_persistent_shell_execute,
    send_persistent_shell_input_execute,
    start_persistent_shell_execute,
)
from ...remote.service import call_remote_worker_tool
from ...terminal.bridge import (
    TERMINAL_BRIDGE_MAX_CHUNK_BYTES,
    TerminalBridgeBusyError,
    TerminalBridgeNotFoundError,
    TerminalBridgeUnsupportedError,
    close_terminal_bridge_execute,
    open_terminal_bridge_execute,
    read_terminal_bridge_execute,
    resize_terminal_bridge_execute,
    write_terminal_bridge_execute,
)
from ...terminal.contracts import (
    PERSISTENT_SHELL_MAX_COLUMNS,
    PERSISTENT_SHELL_MAX_ROWS,
    PERSISTENT_SHELL_MIN_COLUMNS,
    PERSISTENT_SHELL_MIN_ROWS,
)
from .common import bounded_text as _bounded_text
from .common import json_error as _json_error
from .common import require_remote_machine as _require_remote_machine
from .live_state import human_ui_runtime
from .session import has_valid_ui_origin, ui_session_claims
from .terminal_protocol import (
    _BRIDGE_ID_PATTERN,
    UI_TERMINAL_DEFAULT_LINES,
    UI_TERMINAL_INPUT_MAX_BYTES,
    UI_TERMINAL_METADATA_MAX_BYTES,
    UI_TERMINAL_OUTPUT_MAX_BYTES,
    UI_TERMINAL_RAW_READ_WAIT_MS,
    UI_TERMINAL_READ_MAX_LINES,
    UI_TERMINAL_REMOTE_TIMEOUT_S,
    UI_TERMINAL_SUBPROTOCOL,
    _bounded_int,
    _machine_arg,
    _normalize_bridge_close,
    _normalize_bridge_open,
    _normalize_bridge_read,
    _normalize_bridge_resize,
    _normalize_bridge_write,
    _normalize_kill,
    _normalize_list,
    _normalize_read,
    _normalize_resize,
    _normalize_send,
    _normalize_start,
    _remote_result_data,
    _shell_id,
    _TerminalBridgeHandle,
    _websocket_protocols,
    _websocket_token,
    parse_terminal_websocket_request,
)
from .terminal_websocket import (
    TerminalWebSocketBackend,
    serve_terminal_websocket,
)

__all__ = [
    "UI_TERMINAL_INPUT_MAX_BYTES",
    "UI_TERMINAL_OUTPUT_MAX_BYTES",
    "UI_TERMINAL_SUBPROTOCOL",
    "TerminalBridgeBusyError",
    "TerminalBridgeNotFoundError",
    "TerminalBridgeUnsupportedError",
    "_TerminalBridgeHandle",
    "_normalize_bridge_open",
    "_normalize_bridge_read",
    "_normalize_bridge_resize",
    "_normalize_read",
    "_remote_result_data",
    "_websocket_protocols",
]


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _terminal_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ConnectionError):
        return _json_error(exc, status_code=503)
    if isinstance(exc, RuntimeError):
        return _json_error(exc, status_code=502)
    return _json_error(exc)


def _require_scopes(*required: str) -> None:
    try:
        require_oauth_scopes(tuple(dict.fromkeys(required)))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _require_terminal_scopes(machine: str, *, execute: bool = False) -> None:
    required = [SCOPE_SHELL_READ]
    if execute:
        required.append(SCOPE_SHELL_EXECUTE)
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    _require_scopes(*required)


def _remote_timeout_s() -> int:
    return max(
        1,
        min(
            int(get_settings().remote_job_timeout_s),
            UI_TERMINAL_REMOTE_TIMEOUT_S,
        ),
    )


async def _remote_terminal_call(
    machine: str, tool: str, args: dict[str, Any]
) -> Any:
    _require_remote_machine(machine)
    result = await call_remote_worker_tool(
        machine,
        tool,
        args,
        _remote_timeout_s(),
    )
    return _remote_result_data(result, machine=machine, tool=tool)


async def _list_shells(machine: str) -> dict[str, Any]:
    if machine == "local":
        value = await list_persistent_shells_execute()
    else:
        value = await _remote_terminal_call(
            machine, "list_persistent_shells", {}
        )
    return _normalize_list(machine, value)


async def _start_shell(
    machine: str,
    *,
    cwd: str,
    name: str | None,
    command: str | None,
) -> dict[str, Any]:
    if machine == "local":
        value = await start_persistent_shell_execute(cwd, name, command)
    else:
        value = await _remote_terminal_call(
            machine,
            "start_persistent_shell",
            {"cwd": cwd, "name": name, "command": command},
        )
    return _normalize_start(machine, value)


async def _send_shell(
    machine: str,
    shell_id: str,
    input_text: str,
    enter: bool,
) -> dict[str, Any]:
    if machine == "local":
        value = await send_persistent_shell_input_execute(
            shell_id, input_text, enter
        )
    else:
        value = await _remote_terminal_call(
            machine,
            "send_persistent_shell_input",
            {
                "shell_id": shell_id,
                "input_text": input_text,
                "enter": enter,
            },
        )
    return _normalize_send(machine, shell_id, value)


async def _resize_shell(
    machine: str,
    shell_id: str,
    cols: int,
    rows: int,
) -> dict[str, Any]:
    if machine == "local":
        value = await resize_persistent_shell_execute(shell_id, cols, rows)
    else:
        value = await _remote_terminal_call(
            machine,
            "resize_persistent_shell",
            {"shell_id": shell_id, "cols": cols, "rows": rows},
        )
    return _normalize_resize(machine, shell_id, cols, rows, value)


async def _read_shell(
    machine: str,
    shell_id: str,
    lines: int,
) -> dict[str, Any]:
    if machine == "local":
        value = await read_persistent_shell_output_execute(
            shell_id,
            lines,
            preserve_ansi=True,
        )
    else:
        value = await _remote_terminal_call(
            machine,
            "read_persistent_shell_output",
            {"shell_id": shell_id, "lines": lines, "preserve_ansi": True},
        )
    return _normalize_read(machine, shell_id, lines, value)


async def _kill_shell(machine: str, shell_id: str) -> dict[str, Any]:
    if machine == "local":
        value = await kill_persistent_shell_execute(shell_id)
    else:
        value = await _remote_terminal_call(
            machine,
            "kill_persistent_shell",
            {"shell_id": shell_id},
        )
    return _normalize_kill(machine, shell_id, value)


async def _discard_open_bridge(machine: str, value: Any) -> None:
    if not isinstance(value, dict):
        return
    bridge_id = str(value.get("bridge_id") or "")
    if not _BRIDGE_ID_PATTERN.fullmatch(bridge_id):
        return
    with contextlib.suppress(Exception):
        if machine == "local":
            await close_terminal_bridge_execute(bridge_id)
        else:
            await _remote_terminal_call(
                machine,
                "close_terminal_bridge",
                {"bridge_id": bridge_id},
            )


async def _open_bridge(
    machine: str,
    shell_id: str,
    cols: int,
    rows: int,
) -> _TerminalBridgeHandle:
    if machine == "local":
        value = await open_terminal_bridge_execute(shell_id, cols, rows)
    else:
        value = await _remote_terminal_call(
            machine,
            "open_terminal_bridge",
            {"shell_id": shell_id, "cols": cols, "rows": rows},
        )
    try:
        return _normalize_bridge_open(machine, shell_id, cols, rows, value)
    except Exception:
        await _discard_open_bridge(machine, value)
        raise


async def _read_bridge(
    handle: _TerminalBridgeHandle,
) -> tuple[bytes, bool]:
    args = {
        "bridge_id": handle.bridge_id,
        "max_bytes": TERMINAL_BRIDGE_MAX_CHUNK_BYTES,
        "wait_ms": UI_TERMINAL_RAW_READ_WAIT_MS,
    }
    if handle.machine == "local":
        value = await read_terminal_bridge_execute(**args)
    else:
        value = await _remote_terminal_call(
            handle.machine,
            "read_terminal_bridge",
            args,
        )
    return _normalize_bridge_read(handle, value)


async def _write_bridge(
    handle: _TerminalBridgeHandle,
    data: bytes,
) -> None:
    if len(data) > UI_TERMINAL_INPUT_MAX_BYTES:
        raise ValueError("Terminal input is too large")
    encoded = base64.b64encode(data).decode("ascii")
    args = {"bridge_id": handle.bridge_id, "data_b64": encoded}
    if handle.machine == "local":
        value = await write_terminal_bridge_execute(**args)
    else:
        value = await _remote_terminal_call(
            handle.machine,
            "write_terminal_bridge",
            args,
        )
    _normalize_bridge_write(handle, value, len(data))


async def _resize_bridge(
    handle: _TerminalBridgeHandle,
    cols: int,
    rows: int,
) -> None:
    args = {"bridge_id": handle.bridge_id, "cols": cols, "rows": rows}
    if handle.machine == "local":
        value = await resize_terminal_bridge_execute(**args)
    else:
        value = await _remote_terminal_call(
            handle.machine,
            "resize_terminal_bridge",
            args,
        )
    _normalize_bridge_resize(handle, value, cols, rows)


async def _close_bridge(handle: _TerminalBridgeHandle) -> None:
    args = {"bridge_id": handle.bridge_id}
    if handle.machine == "local":
        value = await close_terminal_bridge_execute(**args)
    else:
        value = await _remote_terminal_call(
            handle.machine,
            "close_terminal_bridge",
            args,
        )
    _normalize_bridge_close(handle, value)


def _authorize_websocket(
    websocket: WebSocket, machine: str
) -> tuple[bool, int, str]:
    """Authorize a browser WebSocket without trusting localhost proxy hops."""
    if get_settings().auth_mode == "none":
        return True, 1000, ""

    token = _websocket_token(websocket)
    if token:
        try:
            claims = validate_bearer_token(token)
        except jwt.PyJWTError:
            return False, 4401, "Invalid OAuth bearer token"
    else:
        if not websocket.headers.get("origin", "").strip():
            return False, 4401, "OAuth authentication required"
        if not has_valid_ui_origin(websocket):
            return False, 4403, "Invalid Human UI WebSocket origin"
        try:
            claims = ui_session_claims(websocket)
        except jwt.PyJWTError:
            return False, 4401, "Invalid Human UI session"
        if claims is None:
            return False, 4401, "OAuth authentication required"

    granted = scope_set(str(claims.get("scope") or ""))
    required = [SCOPE_SHELL_READ, SCOPE_SHELL_EXECUTE]
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    for scope in required:
        if scope not in granted:
            return False, 4403, f"Missing required OAuth scope: {scope}"
    return True, 1000, ""


def _reserve_connection() -> int | None:
    maximum = get_settings().ui_terminal_max_connections
    return human_ui_runtime().terminal_connections.reserve(maximum)


def _release_connection(marker: int) -> None:
    human_ui_runtime().terminal_connections.release(marker)


async def api_terminals(request: Request) -> Response:
    """List persistent shells for one selected local or remote machine."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_terminal_scopes(machine)
        return _json_ok(await _list_shells(machine))
    except HTTPException:
        raise
    except Exception as exc:
        return _terminal_error(exc)


async def api_terminal_read(request: Request) -> Response:
    """Return a bounded recent snapshot from one machine-scoped shell."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_terminal_scopes(machine)
        shell_id = _shell_id(request.query_params.get("shell_id"))
        lines = _bounded_int(
            request.query_params.get("lines"),
            default=UI_TERMINAL_DEFAULT_LINES,
            minimum=1,
            maximum=UI_TERMINAL_READ_MAX_LINES,
            label="lines",
        )
        return _json_ok(await _read_shell(machine, shell_id, lines))
    except HTTPException:
        raise
    except Exception as exc:
        return _terminal_error(exc)


async def api_terminal_action(request: Request) -> Response:
    """Start, write, resize, or terminate a machine-scoped shell."""
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        machine = _machine_arg(body.get("machine"))
        _require_terminal_scopes(machine, execute=True)
        match action:
            case "start":
                name = (
                    _bounded_text(
                        body.get("name"),
                        field="name",
                        max_bytes=64,
                    )
                    if body.get("name") is not None
                    else None
                )
                command = (
                    _bounded_text(
                        body.get("command"),
                        field="command",
                        max_bytes=UI_TERMINAL_METADATA_MAX_BYTES,
                    )
                    if body.get("command") is not None
                    else None
                )
                result = await _start_shell(
                    machine,
                    cwd=_bounded_text(
                        body.get("cwd"),
                        field="cwd",
                        max_bytes=UI_TERMINAL_METADATA_MAX_BYTES,
                        default=".",
                        allow_empty=False,
                    ),
                    name=name or None,
                    command=command or None,
                )
            case "send":
                shell_id = _shell_id(body.get("shell_id"))
                input_text = str(body.get("input_text") or "")
                if (
                    len(input_text.encode("utf-8"))
                    > UI_TERMINAL_INPUT_MAX_BYTES
                ):
                    raise ValueError(
                        f"input_text exceeds {UI_TERMINAL_INPUT_MAX_BYTES} encoded bytes"
                    )
                result = await _send_shell(
                    machine,
                    shell_id,
                    input_text,
                    bool(body.get("enter", True)),
                )
            case "resize":
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
                result = await _resize_shell(machine, shell_id, cols, rows)
            case "kill":
                result = await _kill_shell(
                    machine,
                    _shell_id(body.get("shell_id")),
                )
            case _:
                raise ValueError(f"Unsupported terminal action: {action}")
        return _json_ok(result)
    except HTTPException:
        raise
    except Exception as exc:
        return _terminal_error(exc)


async def ui_terminal_websocket(websocket: WebSocket) -> None:
    """Bridge one machine-scoped shell using snapshots or a raw PTY stream."""
    try:
        request = parse_terminal_websocket_request(
            machine=websocket.query_params.get("machine"),
            shell_id=websocket.path_params.get("shell_id"),
            mode=websocket.query_params.get("mode"),
            lines=websocket.query_params.get("lines"),
            cols=websocket.query_params.get("cols"),
            rows=websocket.query_params.get("rows"),
        )
    except ValueError as exc:
        await websocket.close(code=4400, reason=str(exc)[:120])
        return

    backend = TerminalWebSocketBackend(
        list_shells=_list_shells,
        read_shell=_read_shell,
        send_shell=_send_shell,
        resize_shell=_resize_shell,
        open_bridge=_open_bridge,
        read_bridge=_read_bridge,
        write_bridge=_write_bridge,
        resize_bridge=_resize_bridge,
        close_bridge=_close_bridge,
    )
    await serve_terminal_websocket(
        websocket,
        request,
        backend=backend,
        authorize=_authorize_websocket,
        reserve_connection=_reserve_connection,
        release_connection=_release_connection,
        idle_timeout_s=get_settings().ui_terminal_idle_timeout_s,
        audit_event=audit,
    )
