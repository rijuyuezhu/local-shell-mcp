"""Authenticated machine-aware Human UI terminal APIs and tmux bridge."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket, WebSocketDisconnect

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
from ...remote.service import call_remote_worker_tool
from ...schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)
from ...terminal_bridge import (
    TERMINAL_BRIDGE_BACKENDS,
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
from .ui_common import (
    bounded_text as _bounded_text,
)
from .ui_common import (
    json_error as _json_error,
)
from .ui_common import (
    require_remote_machine as _require_remote_machine,
)

UI_TERMINAL_SUBPROTOCOL = "lsm-ui-terminal"
UI_TERMINAL_INPUT_MAX_BYTES = 65_536
UI_TERMINAL_READ_MAX_LINES = 5_000
UI_TERMINAL_DEFAULT_LINES = 1_000
UI_TERMINAL_POLL_INTERVAL_S = 0.25
UI_TERMINAL_REMOTE_POLL_INTERVAL_S = 0.75
UI_TERMINAL_MACHINE_MAX_BYTES = 255
UI_TERMINAL_METADATA_MAX_BYTES = 4_096
UI_TERMINAL_OUTPUT_MAX_BYTES = 4_000_000
UI_TERMINAL_MAX_SHELLS = 256
UI_TERMINAL_REMOTE_TIMEOUT_S = 60
UI_TERMINAL_RAW_READ_WAIT_MS = 100
UI_TERMINAL_MODES = frozenset({"snapshot", "auto", "pty"})
_SHELL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_BRIDGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_CONNECTION_IDS = itertools.count(1)
_ACTIVE_CONNECTIONS: set[int] = set()
_ACTIVE_CONNECTIONS_LOCK = threading.Lock()


@dataclass(frozen=True)
class _TerminalBridgeHandle:
    machine: str
    shell_id: str
    bridge_id: str
    cols: int
    rows: int
    backend: str


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


def _optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = _bounded_text(
        value,
        field=field,
        max_bytes=UI_TERMINAL_METADATA_MAX_BYTES,
    )
    return normalized or None


def _machine_arg(value: Any) -> str:
    return _bounded_text(
        value,
        field="machine",
        max_bytes=UI_TERMINAL_MACHINE_MAX_BYTES,
        default="local",
        allow_empty=False,
    )


def _shell_id(value: Any) -> str:
    shell_id = str(value or "")
    if not _SHELL_ID_PATTERN.fullmatch(shell_id):
        raise ValueError(
            "shell_id must be 1-64 characters using letters, digits, '.', '_' or '-'"
        )
    return shell_id


def _terminal_mode(value: Any) -> str:
    mode = str(value or "snapshot").strip().lower()
    if mode not in UI_TERMINAL_MODES:
        raise ValueError("mode must be one of: snapshot, auto, pty")
    return mode


def _remote_timeout_s() -> int:
    return max(
        1,
        min(
            int(get_settings().remote_job_timeout_s),
            UI_TERMINAL_REMOTE_TIMEOUT_S,
        ),
    )


def _remote_error_text(value: Any, *, fallback: str) -> str:
    try:
        return _bounded_text(
            value,
            field="remote terminal error",
            max_bytes=UI_TERMINAL_METADATA_MAX_BYTES,
            default=fallback,
            allow_empty=False,
        )
    except ValueError:
        return "Remote terminal error exceeded the response limit"


def _raise_remote_terminal_error(
    *,
    tool: str,
    error_type: str,
    message: str,
) -> None:
    if "terminal_bridge" in tool:
        normalized_message = message.lower()
        if error_type in {"TerminalBridgeUnsupportedError", "ValueError"} and (
            "unsupported remote worker tool" in normalized_message
            or "require posix pty" in normalized_message
        ):
            raise TerminalBridgeUnsupportedError(message)
        if error_type == "TerminalBridgeBusyError":
            raise TerminalBridgeBusyError(message)
        if error_type == "TerminalBridgeNotFoundError":
            raise TerminalBridgeNotFoundError(message)
    raise RuntimeError(f"{error_type}: {message}")


def _remote_result_data(result: Any, *, machine: str, tool: str) -> Any:
    fallback = f"remote {tool} failed on {machine}"
    if not isinstance(result, dict):
        raise RuntimeError(
            f"Remote machine {machine} returned a malformed terminal envelope"
        )
    if not result.get("ok", False):
        message = _remote_error_text(result.get("message"), fallback=fallback)
        error_type = _remote_error_text(
            result.get("error"), fallback="remote_error"
        )
        _raise_remote_terminal_error(
            tool=tool,
            error_type=error_type,
            message=message,
        )
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        error_type = _remote_error_text(
            data.get("error_type"), fallback="remote_error"
        )
        message = _remote_error_text(data.get("message"), fallback=fallback)
        _raise_remote_terminal_error(
            tool=tool,
            error_type=error_type,
            message=message,
        )
    return data


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


def _validate_model(model_type: Any, value: Any, *, label: str) -> Any:
    try:
        return model_type.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Machine returned malformed terminal {label}"
        ) from exc


def _normalize_shell_info(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        raw = value.model_dump(mode="json")
    elif isinstance(value, dict):
        raw = value
    else:
        raise RuntimeError("Machine returned malformed terminal inventory")
    try:
        shell_id = _shell_id(raw.get("shell_id"))
        return {
            "shell_id": shell_id,
            "name": _optional_text(raw.get("name"), field="shell name"),
            "cwd": _optional_text(raw.get("cwd"), field="shell cwd"),
            "command": _optional_text(
                raw.get("command"), field="shell command"
            ),
        }
    except ValueError as exc:
        raise RuntimeError(
            "Machine returned malformed terminal inventory"
        ) from exc


def _normalize_list(machine: str, value: Any) -> dict[str, Any]:
    model = _validate_model(
        ListPersistentShellsOutput,
        value,
        label="inventory",
    )
    if len(model.shells) > UI_TERMINAL_MAX_SHELLS:
        raise RuntimeError("Machine returned too many terminal sessions")
    shells = [_normalize_shell_info(item) for item in model.shells]
    identifiers = [item["shell_id"] for item in shells]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("Machine returned duplicate terminal sessions")
    return {
        "machine": machine,
        "remote": machine != "local",
        "shells": shells,
    }


def _normalize_start(machine: str, value: Any) -> dict[str, Any]:
    model = _validate_model(
        StartPersistentShellOutput, value, label="start data"
    )
    try:
        shell_id = _shell_id(model.shell_id)
        return {
            "machine": machine,
            "remote": machine != "local",
            "shell_id": shell_id,
            "name": _optional_text(model.name, field="shell name"),
            "cwd": _optional_text(model.cwd, field="shell cwd"),
            "command": _optional_text(model.command, field="shell command"),
        }
    except ValueError as exc:
        raise RuntimeError(
            "Machine returned malformed terminal start data"
        ) from exc


def _normalize_send(machine: str, shell_id: str, value: Any) -> dict[str, Any]:
    model = _validate_model(
        SendPersistentShellInputOutput,
        value,
        label="send data",
    )
    try:
        returned_shell = _shell_id(model.shell_id)
    except ValueError as exc:
        raise RuntimeError(
            "Machine returned malformed terminal send data"
        ) from exc
    if (
        returned_shell != shell_id
        or not 0 <= model.sent_bytes <= UI_TERMINAL_INPUT_MAX_BYTES
    ):
        raise RuntimeError("Machine returned malformed terminal send data")
    return {
        "machine": machine,
        "remote": machine != "local",
        "shell_id": returned_shell,
        "sent_bytes": model.sent_bytes,
        "enter": model.enter,
    }


def _normalize_resize(
    machine: str,
    shell_id: str,
    cols: int,
    rows: int,
    value: Any,
) -> dict[str, Any]:
    model = _validate_model(
        ResizePersistentShellOutput,
        value,
        label="resize data",
    )
    try:
        returned_shell = _shell_id(model.shell_id)
    except ValueError as exc:
        raise RuntimeError(
            "Machine returned malformed terminal resize data"
        ) from exc
    if returned_shell != shell_id or model.cols != cols or model.rows != rows:
        raise RuntimeError("Machine returned malformed terminal resize data")
    return {
        "machine": machine,
        "remote": machine != "local",
        "shell_id": returned_shell,
        "cols": model.cols,
        "rows": model.rows,
        "resized": model.resized,
        "backend": model.backend,
    }


def _normalize_read(
    machine: str,
    shell_id: str,
    lines: int,
    value: Any,
) -> dict[str, Any]:
    model = _validate_model(ReadPersistentShellOutput, value, label="read data")
    try:
        returned_shell = _shell_id(model.shell_id)
    except ValueError as exc:
        raise RuntimeError(
            "Machine returned malformed terminal read data"
        ) from exc
    if returned_shell != shell_id:
        raise RuntimeError("Machine returned malformed terminal read data")
    output = str(model.output or "")
    if len(output.encode("utf-8")) > UI_TERMINAL_OUTPUT_MAX_BYTES:
        raise RuntimeError("Machine returned oversized terminal output")
    return {
        "machine": machine,
        "remote": machine != "local",
        "shell_id": returned_shell,
        "output": output,
        "lines": lines,
    }


def _normalize_kill(machine: str, shell_id: str, value: Any) -> dict[str, Any]:
    model = _validate_model(KillPersistentShellOutput, value, label="kill data")
    try:
        returned_shell = _shell_id(model.shell_id)
        stderr = _optional_text(model.stderr, field="terminal stderr")
    except ValueError as exc:
        raise RuntimeError(
            "Machine returned malformed terminal kill data"
        ) from exc
    if returned_shell != shell_id:
        raise RuntimeError("Machine returned malformed terminal kill data")
    return {
        "machine": machine,
        "remote": machine != "local",
        "shell_id": returned_shell,
        "killed": model.killed,
        "stderr": stderr,
    }


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


def _bridge_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(
            f"Machine returned malformed terminal bridge {label}"
        )
    return value


def _bridge_result_id(value: Any, *, expected: str | None = None) -> str:
    bridge_id = str(value or "")
    if not _BRIDGE_ID_PATTERN.fullmatch(bridge_id):
        raise RuntimeError(
            "Machine returned malformed terminal bridge capability"
        )
    if expected is not None and bridge_id != expected:
        raise RuntimeError(
            "Machine returned mismatched terminal bridge capability"
        )
    return bridge_id


def _normalize_bridge_open(
    machine: str,
    shell_id: str,
    cols: int,
    rows: int,
    value: Any,
) -> _TerminalBridgeHandle:
    data = _bridge_mapping(value, label="open data")
    bridge_id = _bridge_result_id(data.get("bridge_id"))
    try:
        returned_shell = _shell_id(data.get("shell_id"))
        returned_cols = int(str(data.get("cols") or ""))
        returned_rows = int(str(data.get("rows") or ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Machine returned malformed terminal bridge open data"
        ) from exc
    backend = str(data.get("backend") or "")
    if (
        returned_shell != shell_id
        or returned_cols != cols
        or returned_rows != rows
        or backend not in TERMINAL_BRIDGE_BACKENDS
    ):
        raise RuntimeError(
            "Machine returned malformed terminal bridge open data"
        )
    return _TerminalBridgeHandle(
        machine=machine,
        shell_id=shell_id,
        bridge_id=bridge_id,
        cols=cols,
        rows=rows,
        backend=backend,
    )


def _normalize_bridge_read(
    handle: _TerminalBridgeHandle,
    value: Any,
) -> tuple[bytes, bool]:
    data = _bridge_mapping(value, label="read data")
    _bridge_result_id(data.get("bridge_id"), expected=handle.bridge_id)
    encoded = data.get("data_b64")
    if not isinstance(encoded, str) or len(encoded) > 90_000:
        raise RuntimeError(
            "Machine returned malformed terminal bridge read data"
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
        count = int(str(data.get("bytes")))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Machine returned malformed terminal bridge read data"
        ) from exc
    eof = data.get("eof")
    if (
        not isinstance(eof, bool)
        or count != len(raw)
        or len(raw) > TERMINAL_BRIDGE_MAX_CHUNK_BYTES
    ):
        raise RuntimeError(
            "Machine returned malformed terminal bridge read data"
        )
    return raw, eof


def _normalize_bridge_write(
    handle: _TerminalBridgeHandle,
    value: Any,
    expected_bytes: int,
) -> None:
    data = _bridge_mapping(value, label="write data")
    _bridge_result_id(data.get("bridge_id"), expected=handle.bridge_id)
    try:
        written = int(str(data.get("written_bytes") or ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Machine returned malformed terminal bridge write data"
        ) from exc
    if written != expected_bytes:
        raise RuntimeError(
            "Machine returned malformed terminal bridge write data"
        )


def _normalize_bridge_resize(
    handle: _TerminalBridgeHandle,
    value: Any,
    cols: int,
    rows: int,
) -> None:
    data = _bridge_mapping(value, label="resize data")
    _bridge_result_id(data.get("bridge_id"), expected=handle.bridge_id)
    try:
        returned_cols = int(str(data.get("cols") or ""))
        returned_rows = int(str(data.get("rows") or ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Machine returned malformed terminal bridge resize data"
        ) from exc
    resized = data.get("resized")
    if (
        returned_cols != cols
        or returned_rows != rows
        or not isinstance(resized, bool)
        or data.get("backend") != handle.backend
    ):
        raise RuntimeError(
            "Machine returned malformed terminal bridge resize data"
        )


def _normalize_bridge_close(
    handle: _TerminalBridgeHandle,
    value: Any,
) -> None:
    data = _bridge_mapping(value, label="close data")
    _bridge_result_id(data.get("bridge_id"), expected=handle.bridge_id)
    if not isinstance(data.get("closed"), bool):
        raise RuntimeError(
            "Machine returned malformed terminal bridge close data"
        )


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


def _authorize_websocket(
    websocket: WebSocket, machine: str
) -> tuple[bool, int, str]:
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
    required = [SCOPE_SHELL_READ, SCOPE_SHELL_EXECUTE]
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    for scope in required:
        if scope not in granted:
            return False, 4403, f"Missing required OAuth scope: {scope}"
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
        if action == "start":
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
        elif action == "send":
            shell_id = _shell_id(body.get("shell_id"))
            input_text = str(body.get("input_text") or "")
            if len(input_text.encode("utf-8")) > UI_TERMINAL_INPUT_MAX_BYTES:
                raise ValueError(
                    f"input_text exceeds {UI_TERMINAL_INPUT_MAX_BYTES} encoded bytes"
                )
            result = await _send_shell(
                machine,
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
            result = await _resize_shell(machine, shell_id, cols, rows)
        elif action == "kill":
            result = await _kill_shell(
                machine,
                _shell_id(body.get("shell_id")),
            )
        else:
            raise ValueError(f"Unsupported terminal action: {action}")
        return _json_ok(result)
    except HTTPException:
        raise
    except Exception as exc:
        return _terminal_error(exc)


async def ui_terminal_websocket(websocket: WebSocket) -> None:
    """Bridge one machine-scoped shell using snapshots or a raw PTY stream."""
    try:
        machine = _machine_arg(websocket.query_params.get("machine"))
        shell_id = _shell_id(websocket.path_params.get("shell_id"))
        raw_mode = websocket.query_params.get("mode")
        requested_mode = _terminal_mode(raw_mode)
        announce_mode = raw_mode is not None
        lines = _bounded_int(
            websocket.query_params.get("lines"),
            default=UI_TERMINAL_DEFAULT_LINES,
            minimum=1,
            maximum=UI_TERMINAL_READ_MAX_LINES,
            label="lines",
        )
        current_cols = _bounded_int(
            websocket.query_params.get("cols"),
            default=120,
            minimum=PERSISTENT_SHELL_MIN_COLUMNS,
            maximum=PERSISTENT_SHELL_MAX_COLUMNS,
            label="cols",
        )
        current_rows = _bounded_int(
            websocket.query_params.get("rows"),
            default=36,
            minimum=PERSISTENT_SHELL_MIN_ROWS,
            maximum=PERSISTENT_SHELL_MAX_ROWS,
            label="rows",
        )
    except ValueError as exc:
        await websocket.close(code=4400, reason=str(exc)[:120])
        return

    authorized, close_code, reason = _authorize_websocket(websocket, machine)
    if not authorized:
        await websocket.close(code=close_code, reason=reason[:120])
        return

    try:
        shells = await _list_shells(machine)
    except ConnectionError as exc:
        await websocket.close(code=1013, reason=str(exc)[:120])
        return
    except ValueError as exc:
        await websocket.close(code=4404, reason=str(exc)[:120])
        return
    except Exception:
        await websocket.close(
            code=1011, reason="Unable to inspect persistent shells"
        )
        return
    if shell_id not in {item["shell_id"] for item in shells["shells"]}:
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

    bridge: _TerminalBridgeHandle | None = None
    active_mode = "snapshot"
    if requested_mode in {"auto", "pty"}:
        try:
            bridge = await _open_bridge(
                machine,
                shell_id,
                current_cols,
                current_rows,
            )
            active_mode = "pty"
        except TerminalBridgeUnsupportedError as exc:
            if requested_mode == "pty":
                _release_connection(marker)
                await websocket.close(code=4406, reason=str(exc)[:120])
                return
        except TerminalBridgeBusyError as exc:
            _release_connection(marker)
            await websocket.close(code=4409, reason=str(exc)[:120])
            return
        except ConnectionError as exc:
            _release_connection(marker)
            await websocket.close(code=1013, reason=str(exc)[:120])
            return
        except Exception as exc:
            _release_connection(marker)
            await websocket.close(code=1011, reason=str(exc)[:120])
            return

    send_lock = asyncio.Lock()
    settings = get_settings()
    last_activity = time.monotonic()
    cleaned_up = False
    audit(
        "ui_terminal_connected",
        machine=machine,
        shell_id=shell_id,
        requested_mode=requested_mode,
        mode=active_mode,
    )

    async def cleanup_connection() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        if bridge is not None:
            with contextlib.suppress(Exception):
                await _close_bridge(bridge)
        _release_connection(marker)
        audit(
            "ui_terminal_disconnected",
            machine=machine,
            shell_id=shell_id,
            mode=active_mode,
        )
        with contextlib.suppress(Exception):
            await websocket.close()

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def send_bytes(payload: bytes) -> None:
        async with send_lock:
            await websocket.send_bytes(payload)

    def touch() -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

    async def send_exit(exc: Exception) -> None:
        payload: dict[str, Any] = {
            "type": "exit",
            "machine": machine,
            "shell_id": shell_id,
            "message": str(exc)[:UI_TERMINAL_METADATA_MAX_BYTES],
        }
        if announce_mode:
            payload["mode"] = active_mode
        await send_json(payload)

    if announce_mode:
        try:
            await send_json(
                {
                    "type": "ready",
                    "machine": machine,
                    "shell_id": shell_id,
                    "mode": active_mode,
                    "backend": (
                        bridge.backend
                        if bridge is not None
                        else "tmux-snapshot"
                    ),
                }
            )
        except Exception:
            await cleanup_connection()
            return

    async def snapshot_sender() -> None:
        previous: str | None = None
        interval = (
            UI_TERMINAL_POLL_INTERVAL_S
            if machine == "local"
            else UI_TERMINAL_REMOTE_POLL_INTERVAL_S
        )
        while True:
            try:
                result = await _read_shell(machine, shell_id, lines)
            except Exception as exc:
                await send_exit(exc)
                return
            output = str(result["output"])
            if output != previous:
                previous = output
                touch()
                await send_json(
                    {
                        "type": "snapshot",
                        "machine": machine,
                        "shell_id": shell_id,
                        "output": output,
                    }
                )
            await asyncio.sleep(interval)

    async def pty_sender() -> None:
        if bridge is None:
            raise RuntimeError("Raw terminal bridge was not initialized")
        while True:
            try:
                data, eof = await _read_bridge(bridge)
            except Exception as exc:
                await send_exit(exc)
                return
            if data:
                touch()
                await send_bytes(data)
            if eof:
                await send_exit(
                    TerminalBridgeNotFoundError("Raw terminal client exited")
                )
                return

    async def receiver() -> None:
        nonlocal current_cols, current_rows
        idle_timeout = max(0, settings.ui_terminal_idle_timeout_s)
        try:
            while True:
                try:
                    if idle_timeout:
                        remaining = max(
                            0.0,
                            idle_timeout - (time.monotonic() - last_activity),
                        )
                        if remaining <= 0:
                            await websocket.close(
                                code=4408,
                                reason="Terminal connection idle timeout",
                            )
                            return
                        message = await asyncio.wait_for(
                            websocket.receive(), timeout=remaining
                        )
                    else:
                        message = await websocket.receive()
                except TimeoutError:
                    if (
                        idle_timeout
                        and time.monotonic() - last_activity < idle_timeout
                    ):
                        continue
                    await websocket.close(
                        code=4408, reason="Terminal connection idle timeout"
                    )
                    return
                if message["type"] == "websocket.disconnect":
                    return
                touch()

                if message.get("bytes") is not None:
                    raw = bytes(message["bytes"])
                    if len(raw) > UI_TERMINAL_INPUT_MAX_BYTES:
                        await websocket.close(
                            code=4400, reason="Terminal input is too large"
                        )
                        return
                    if active_mode == "pty":
                        if bridge is None:
                            raise RuntimeError(
                                "Raw terminal bridge was not initialized"
                            )
                        await _write_bridge(bridge, raw)
                    else:
                        await _send_shell(
                            machine,
                            shell_id,
                            raw.decode("utf-8", errors="replace"),
                            False,
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
                    raw_input = input_text.encode("utf-8")
                    enter = bool(control.get("enter", False))
                    if active_mode == "pty" and enter:
                        raw_input += b"\r"
                    if len(raw_input) > UI_TERMINAL_INPUT_MAX_BYTES:
                        await websocket.close(
                            code=4400, reason="Terminal input is too large"
                        )
                        return
                    if active_mode == "pty":
                        if bridge is None:
                            raise RuntimeError(
                                "Raw terminal bridge was not initialized"
                            )
                        await _write_bridge(bridge, raw_input)
                    else:
                        await _send_shell(
                            machine,
                            shell_id,
                            input_text,
                            enter,
                        )
                elif kind == "resize":
                    try:
                        current_cols = _bounded_int(
                            control.get("cols"),
                            default=current_cols,
                            minimum=PERSISTENT_SHELL_MIN_COLUMNS,
                            maximum=PERSISTENT_SHELL_MAX_COLUMNS,
                            label="cols",
                        )
                        current_rows = _bounded_int(
                            control.get("rows"),
                            default=current_rows,
                            minimum=PERSISTENT_SHELL_MIN_ROWS,
                            maximum=PERSISTENT_SHELL_MAX_ROWS,
                            label="rows",
                        )
                    except ValueError as exc:
                        await websocket.close(code=4400, reason=str(exc)[:120])
                        return
                    if active_mode == "pty":
                        if bridge is None:
                            raise RuntimeError(
                                "Raw terminal bridge was not initialized"
                            )
                        await _resize_bridge(
                            bridge,
                            current_cols,
                            current_rows,
                        )
                    else:
                        await _resize_shell(
                            machine,
                            shell_id,
                            current_cols,
                            current_rows,
                        )
                elif kind == "ping":
                    payload: dict[str, Any] = {
                        "type": "pong",
                        "machine": machine,
                        "shell_id": shell_id,
                    }
                    if announce_mode:
                        payload["mode"] = active_mode
                    await send_json(payload)
                elif kind == "close":
                    return
                else:
                    await websocket.close(
                        code=4400, reason="Unsupported terminal control"
                    )
                    return
        except (
            ConnectionError,
            RuntimeError,
            TerminalBridgeNotFoundError,
            ValueError,
        ) as exc:
            await send_exit(exc)

    sender = pty_sender if active_mode == "pty" else snapshot_sender
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
        await cleanup_connection()
