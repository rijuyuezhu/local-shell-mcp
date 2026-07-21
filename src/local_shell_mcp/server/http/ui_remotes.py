"""Authenticated Human UI control-plane APIs for remote workers."""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...audit import audit
from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import SCOPE_REMOTE_USE
from ...remote.service import (
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)

UI_REMOTE_MAX_MACHINES = 1_024
UI_REMOTE_MACHINE_MAX_CHARS = 128
UI_REMOTE_MACHINE_MAX_BYTES = 512
UI_REMOTE_PATH_MAX_BYTES = 4_096
UI_REMOTE_CAPABILITIES_MAX = 64
UI_REMOTE_CAPABILITY_MAX_BYTES = 128
UI_REMOTE_COMMAND_MAX_BYTES = 16_384
UI_REMOTE_VERSION_MAX_BYTES = 256
UI_REMOTE_SMALL_INFO_MAX_BYTES = 512
UI_REMOTE_INFO_KEYS = {
    "lsm_version": UI_REMOTE_VERSION_MAX_BYTES,
    "hostname": UI_REMOTE_SMALL_INFO_MAX_BYTES,
    "user": UI_REMOTE_SMALL_INFO_MAX_BYTES,
    "python": UI_REMOTE_SMALL_INFO_MAX_BYTES,
    "platform": UI_REMOTE_SMALL_INFO_MAX_BYTES,
    "cwd": UI_REMOTE_PATH_MAX_BYTES,
    "workdir": UI_REMOTE_PATH_MAX_BYTES,
}


class _InviteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    workdir: str | None = None
    ttl_s: int | None = Field(default=None, ge=60, le=24 * 60 * 60)


class _RenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine: str
    new_name: str


class _RevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine: str


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse(
        {"ok": True, "message": message, "data": data},
        headers={"Cache-Control": "no-store"},
    )


def _json_error(error: str, message: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": error, "message": message},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _require_remote_scope() -> None:
    try:
        require_oauth_scopes((SCOPE_REMOTE_USE,))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _bounded_text(
    value: Any,
    *,
    field: str,
    max_bytes: int,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} encoded bytes")
    return text


def _machine_name(value: Any, *, field: str = "machine") -> str:
    name = _bounded_text(
        value,
        field=field,
        max_bytes=UI_REMOTE_MACHINE_MAX_BYTES,
        allow_empty=False,
    )
    if len(name) > UI_REMOTE_MACHINE_MAX_CHARS:
        raise ValueError(
            f"{field} exceeds {UI_REMOTE_MACHINE_MAX_CHARS} characters"
        )
    if any(
        ord(character) < 32 or character in {"/", "\\"} for character in name
    ):
        raise ValueError(f"{field} contains unsupported characters")
    return name


def _optional_path(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    path = _bounded_text(value, field=field, max_bytes=UI_REMOTE_PATH_MAX_BYTES)
    return path or None


def _finite_number(
    value: Any,
    *,
    field: str,
    minimum: float = 0.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{field} must be finite and at least {minimum}")
    return number


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _capabilities(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("capabilities must be a list")
    if len(value) > UI_REMOTE_CAPABILITIES_MAX:
        raise ValueError(
            f"capabilities exceeds {UI_REMOTE_CAPABILITIES_MAX} entries"
        )
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        capability = _bounded_text(
            item,
            field="capability",
            max_bytes=UI_REMOTE_CAPABILITY_MAX_BYTES,
            allow_empty=False,
        )
        if capability not in seen:
            seen.add(capability)
            output.append(capability)
    return output


def _public_info(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("info must be an object")
    output: dict[str, str] = {}
    for key, limit in UI_REMOTE_INFO_KEYS.items():
        raw = value.get(key)
        if raw is None:
            continue
        output[key] = _bounded_text(
            raw,
            field=f"info.{key}",
            max_bytes=limit,
        )
    return output


def _machine_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("remote machine row must be an object")
    status = _bounded_text(
        value.get("status"),
        field="status",
        max_bytes=32,
        allow_empty=False,
    )
    if status not in {"online", "offline"}:
        raise ValueError("status must be online or offline")
    last_seen = _finite_number(value.get("last_seen", 0.0), field="last_seen")
    last_seen_age = value.get("last_seen_age_s")
    offline_after = value.get("offline_after_s")
    return {
        "name": _machine_name(value.get("name")),
        "status": status,
        "workdir": _optional_path(value.get("workdir"), field="workdir"),
        "last_seen": last_seen,
        "last_seen_age_s": None
        if last_seen_age is None
        else _finite_number(last_seen_age, field="last_seen_age_s"),
        "offline_after_s": None
        if offline_after is None
        else _finite_number(offline_after, field="offline_after_s"),
        "queue_depth": _nonnegative_int(
            value.get("queue_depth") or 0, field="queue_depth"
        ),
        "capabilities": _capabilities(value.get("capabilities", [])),
        "info": _public_info(value.get("info", {})),
    }


def _inventory_payload() -> dict[str, Any]:
    settings = get_settings()
    if not settings.remote_enabled:
        return {
            "enabled": False,
            "machines": [],
            "counts": {"online": 0, "offline": 0, "total": 0},
            "invite_ttl_s": settings.remote_invite_ttl_s,
        }
    raw = list_remote_machines().model_dump(mode="json")
    rows = raw.get("machines")
    if not isinstance(rows, list):
        raise RuntimeError("Remote inventory returned an invalid machine list")
    if len(rows) > UI_REMOTE_MAX_MACHINES:
        raise RuntimeError(
            f"Remote inventory exceeds {UI_REMOTE_MAX_MACHINES} machines"
        )
    machines = [_machine_row(row) for row in rows]
    names = [row["name"] for row in machines]
    if len(names) != len(set(names)):
        raise RuntimeError("Remote inventory contains duplicate machine names")
    online = sum(row["status"] == "online" for row in machines)
    return {
        "enabled": True,
        "machines": machines,
        "counts": {
            "online": online,
            "offline": len(machines) - online,
            "total": len(machines),
        },
        "invite_ttl_s": settings.remote_invite_ttl_s,
    }


def _invite_payload(value: Any) -> dict[str, Any]:
    data = value.model_dump(mode="json")
    expires_at = _finite_number(data.get("expires_at"), field="expires_at")
    ttl_s = _nonnegative_int(data.get("ttl_s"), field="ttl_s")
    if ttl_s < 60 or ttl_s > 24 * 60 * 60:
        raise RuntimeError("Remote invite returned an invalid lifetime")
    return {
        "name": None
        if data.get("name") is None
        else _machine_name(data.get("name"), field="name"),
        "workdir": _optional_path(data.get("workdir"), field="workdir"),
        "expires_at": expires_at,
        "ttl_s": ttl_s,
        "command": _bounded_text(
            data.get("command"),
            field="command",
            max_bytes=UI_REMOTE_COMMAND_MAX_BYTES,
            allow_empty=False,
        ),
    }


def _parse_body(model: type[BaseModel], value: Any) -> BaseModel:
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _mutation_disabled() -> JSONResponse:
    return _json_error(
        "RemoteWorkersDisabled",
        "Remote worker support is disabled",
        status_code=409,
    )


async def api_remotes(request: Request) -> Response:
    """List remote workers or create one short-lived enrollment invite."""
    _require_remote_scope()
    if request.method == "GET":
        try:
            return _json_ok(_inventory_payload())
        except Exception:  # noqa: BLE001
            return _json_error(
                "RemoteInventoryUnavailable",
                "Remote worker inventory is unavailable",
                status_code=500,
            )

    if not get_settings().remote_enabled:
        return _mutation_disabled()
    try:
        body = _parse_body(_InviteBody, await request.json())
        assert isinstance(body, _InviteBody)
        name = (
            None
            if body.name is None
            else _machine_name(body.name, field="name")
        )
        workdir = _optional_path(body.workdir, field="workdir")
        result = await create_remote_invite(name, workdir, body.ttl_s)
        payload = _invite_payload(result)
        audit(
            "ui_remote_invite_created",
            machine=name,
            workdir=workdir,
            expires_at=payload["expires_at"],
            ttl_s=payload["ttl_s"],
        )
        return _json_ok(payload, "Remote invite created")
    except ValueError as exc:
        return _json_error(type(exc).__name__, str(exc), status_code=400)
    except RuntimeError as exc:
        if "Too many pending remote invites" in str(exc):
            return _json_error(
                "RemoteInviteCapacityExceeded",
                "Too many pending remote invites",
                status_code=429,
            )
        return _json_error(
            "RemoteInviteUnavailable",
            "Remote invite could not be created",
            status_code=500,
        )
    except Exception:  # noqa: BLE001
        return _json_error(
            "RemoteInviteUnavailable",
            "Remote invite could not be created",
            status_code=500,
        )


async def api_remote_action(request: Request) -> Response:
    """Rename or revoke one registered remote worker."""
    _require_remote_scope()
    if not get_settings().remote_enabled:
        return _mutation_disabled()
    action = str(request.path_params.get("action") or "")
    try:
        raw = await request.json()
        if action == "rename":
            body = _parse_body(_RenameBody, raw)
            assert isinstance(body, _RenameBody)
            machine = _machine_name(body.machine)
            new_name = _machine_name(body.new_name, field="new_name")
            result = rename_remote_machine(machine, new_name)
            payload = result.model_dump(mode="json")
            audit(
                "ui_remote_worker_renamed",
                machine=machine,
                new_name=new_name,
            )
            return _json_ok(payload, "Remote worker renamed")
        if action == "revoke":
            body = _parse_body(_RevokeBody, raw)
            assert isinstance(body, _RevokeBody)
            machine = _machine_name(body.machine)
            result = revoke_remote_machine(machine)
            payload = result.model_dump(mode="json")
            audit("ui_remote_worker_revoked", machine=machine)
            return _json_ok(payload, "Remote worker revoked")
        raise ValueError(f"Unsupported remote action: {action}")
    except ValueError as exc:
        return _json_error(type(exc).__name__, str(exc), status_code=400)
    except Exception:  # noqa: BLE001
        return _json_error(
            "RemoteMutationUnavailable",
            "Remote worker operation failed",
            status_code=500,
        )
