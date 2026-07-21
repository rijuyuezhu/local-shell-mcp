"""Authenticated machine-aware Human UI terminal APIs and tmux bridge."""

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
from ...remote.manager import remote_manager
from ...remote.service import call_remote_worker_tool
from ...schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
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


def _bounded_text(
    value: Any,
    *,
    field: str,
    max_bytes: int,
    default: str = "",
    allow_empty: bool = True,
) -> str:
    normalized = str(value if value is not None else default).strip()
    if not normalized and not allow_empty:
        raise ValueError(f"{field} is required")
    if len(normalized.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} encoded bytes")
    return normalized


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


def _remote_timeout_s() -> int:
    return max(
        1,
        min(
            int(get_settings().remote_job_timeout_s),
            UI_TERMINAL_REMOTE_TIMEOUT_S,
        ),
    )


def _require_remote_machine(machine: str) -> None:
    settings = get_settings()
    if not settings.remote_enabled:
        raise ValueError("Remote workers are disabled")
    inventory = remote_manager().list_machines()
    row = next(
        (item for item in inventory.machines if item.name == machine), None
    )
    if row is None:
        raise ValueError(f"Unknown remote machine: {machine}")
    if row.status != "online":
        raise ConnectionError(f"Remote machine {machine} is {row.status}")


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


def _remote_result_data(result: Any, *, machine: str, tool: str) -> Any:
    fallback = f"remote {tool} failed on {machine}"
    if not isinstance(result, dict):
        raise RuntimeError(
            f"Remote machine {machine} returned a malformed terminal envelope"
        )
    if not result.get("ok", False):
        raise RuntimeError(
            _remote_error_text(result.get("message"), fallback=fallback)
        )
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        error_type = _remote_error_text(
            data.get("error_type"), fallback="remote_error"
        )
        message = _remote_error_text(data.get("message"), fallback=fallback)
        raise RuntimeError(f"{error_type}: {message}")
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
        value = await read_persistent_shell_output_execute(shell_id, lines)
    else:
        value = await _remote_terminal_call(
            machine,
            "read_persistent_shell_output",
            {"shell_id": shell_id, "lines": lines},
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
    """Stream snapshots and ordered controls for one machine-scoped shell."""
    try:
        machine = _machine_arg(websocket.query_params.get("machine"))
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

    send_lock = asyncio.Lock()
    settings = get_settings()
    audit("ui_terminal_connected", machine=machine, shell_id=shell_id)

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def send_exit(exc: Exception) -> None:
        await send_json(
            {
                "type": "exit",
                "machine": machine,
                "shell_id": shell_id,
                "message": str(exc)[:UI_TERMINAL_METADATA_MAX_BYTES],
            }
        )

    async def sender() -> None:
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
                await send_json(
                    {
                        "type": "snapshot",
                        "machine": machine,
                        "shell_id": shell_id,
                        "output": output,
                    }
                )
            await asyncio.sleep(interval)

    async def receiver() -> None:
        idle_timeout = max(0, settings.ui_terminal_idle_timeout_s)
        try:
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
                    if (
                        len(input_text.encode("utf-8"))
                        > UI_TERMINAL_INPUT_MAX_BYTES
                    ):
                        await websocket.close(
                            code=4400, reason="Terminal input is too large"
                        )
                        return
                    await _send_shell(
                        machine,
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
                    await _resize_shell(machine, shell_id, cols, rows)
                elif kind == "ping":
                    await send_json(
                        {
                            "type": "pong",
                            "machine": machine,
                            "shell_id": shell_id,
                        }
                    )
                elif kind == "close":
                    return
                else:
                    await websocket.close(
                        code=4400, reason="Unsupported terminal control"
                    )
                    return
        except (ConnectionError, RuntimeError, ValueError) as exc:
            await send_exit(exc)

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
        audit("ui_terminal_disconnected", machine=machine, shell_id=shell_id)
        with contextlib.suppress(Exception):
            await websocket.close()
