"""Authenticated Human UI API for local and remote Dashboard telemetry."""

import asyncio
import math
from typing import Any, cast

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import SCOPE_REMOTE_USE, SCOPE_SHELL_READ
from ...remote.service import call_remote_worker_tool
from ..dashboard import dashboard_snapshot
from .common import (
    bounded_text as _bounded_text,
)
from .common import (
    json_error as _json_error,
)
from .common import (
    require_remote_machine as _require_remote_machine,
)

UI_DASHBOARD_MACHINE_MAX_BYTES = 255
UI_DASHBOARD_TEXT_MAX_BYTES = 4_096
UI_DASHBOARD_REMOTE_TIMEOUT_S = 60
UI_DASHBOARD_MAX_ALERTS = 12
UI_DASHBOARD_MAX_ACTIVITY = 12

_SYSTEM_NUMBER_FIELDS = (
    "timestamp",
    "cpu_percent",
    "cpu_count",
    "memory_percent",
    "memory_used_bytes",
    "memory_total_bytes",
    "disk_percent",
    "disk_used_bytes",
    "disk_total_bytes",
    "load_1m",
    "network_rx_bps",
    "network_tx_bps",
    "uptime_s",
)


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _require_scopes(*required: str) -> None:
    try:
        require_oauth_scopes(tuple(dict.fromkeys(required)))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _machine_arg(value: Any) -> str:
    return _bounded_text(
        value,
        field="machine",
        max_bytes=UI_DASHBOARD_MACHINE_MAX_BYTES,
        default="local",
        allow_empty=False,
    )


def _remote_timeout_s() -> int:
    return max(
        1,
        min(
            int(get_settings().remote_job_timeout_s),
            UI_DASHBOARD_REMOTE_TIMEOUT_S,
        ),
    )


def _remote_result_data(
    result: dict[str, Any], *, machine: str, tool: str
) -> dict[str, Any]:
    if not result.get("ok", False):
        raise RuntimeError(
            str(result.get("message") or f"remote {tool} failed on {machine}")
        )
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        error_type = str(data.get("error_type") or "remote_error")
        message = str(
            data.get("message") or f"remote {tool} failed on {machine}"
        )
        raise RuntimeError(f"{error_type}: {message}")
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Remote machine {machine} returned malformed dashboard data"
        )
    return cast(dict[str, Any], data)


async def _remote_dashboard_call(machine: str) -> dict[str, Any]:
    _require_remote_machine(machine)
    result = await call_remote_worker_tool(
        machine,
        "dashboard_snapshot",
        {},
        _remote_timeout_s(),
    )
    return _remote_result_data(
        result, machine=machine, tool="dashboard_snapshot"
    )


def _finite_number(
    value: Any,
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Malformed dashboard {field}")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise RuntimeError(f"Malformed dashboard {field}")
    if minimum is not None and normalized < minimum:
        raise RuntimeError(f"Malformed dashboard {field}")
    if maximum is not None and normalized > maximum:
        raise RuntimeError(f"Malformed dashboard {field}")
    if field == "cpu_count":
        if normalized < 1 or not normalized.is_integer():
            raise RuntimeError("Malformed dashboard cpu_count")
        return int(normalized)
    return normalized


def _snapshot_text(
    value: Any,
    *,
    field: str,
    max_bytes: int,
    allow_empty: bool = True,
) -> str:
    try:
        return _bounded_text(
            value,
            field=field,
            max_bytes=max_bytes,
            allow_empty=allow_empty,
        )
    except ValueError as exc:
        raise RuntimeError(f"Malformed dashboard {field}") from exc


def _normalize_system(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Machine returned malformed dashboard system data")
    percentage_fields = {"cpu_percent", "memory_percent", "disk_percent"}
    system: dict[str, Any] = {}
    for field in _SYSTEM_NUMBER_FIELDS:
        system[field] = _finite_number(
            value.get(field),
            field=field,
            minimum=0.0 if field != "cpu_count" else None,
            maximum=100.0 if field in percentage_fields else None,
        )
    return system


def _normalize_version(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RuntimeError("Machine returned malformed dashboard version data")
    version: dict[str, str] = {}
    for field in ("version", "package_version", "python", "platform"):
        if field not in value:
            continue
        version[field] = _snapshot_text(
            value.get(field),
            field=f"version.{field}",
            max_bytes=512,
        )
    return version


def _normalize_alert(machine: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Machine returned a malformed dashboard alert")
    severity = str(value.get("severity") or "info").casefold()
    if severity not in {"info", "warning", "critical"}:
        severity = "info"
    alert: dict[str, Any] = {
        "severity": severity,
        "title": _snapshot_text(
            value.get("title"),
            field="alert title",
            max_bytes=1_024,
            allow_empty=False,
        ),
        "detail": _snapshot_text(
            value.get("detail"),
            field="alert detail",
            max_bytes=UI_DASHBOARD_TEXT_MAX_BYTES,
        ),
        "node": machine,
    }
    if value.get("age_s") is not None:
        alert["age_s"] = _finite_number(
            value.get("age_s"), field="alert age", minimum=0.0
        )
    return alert


def _normalize_activity(machine: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Machine returned malformed dashboard activity")
    kind = str(value.get("kind") or "success").casefold()
    if kind not in {"success", "running", "failed"}:
        kind = "success"
    activity: dict[str, Any] = {
        "timestamp": _finite_number(
            value.get("timestamp"), field="activity timestamp", minimum=0.0
        )
        or 0.0,
        "kind": kind,
        "title": _snapshot_text(
            value.get("title"),
            field="activity title",
            max_bytes=1_024,
            allow_empty=False,
        ),
        "detail": _snapshot_text(
            value.get("detail"),
            field="activity detail",
            max_bytes=1_024,
        ),
        "node": machine,
    }
    if value.get("duration_ms") is not None:
        activity["duration_ms"] = _finite_number(
            value.get("duration_ms"), field="activity duration", minimum=0.0
        )
    return activity


def _bounded_nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Machine returned malformed dashboard {field}")
    return value


def _normalize_snapshot(machine: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard data"
        )
    health = str(value.get("health") or "healthy").casefold()
    if health not in {"healthy", "attention", "critical"}:
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard health"
        )
    raw_alerts = value.get("alerts")
    raw_activity = value.get("activity")
    if (
        not isinstance(raw_alerts, list)
        or len(raw_alerts) > UI_DASHBOARD_MAX_ALERTS
    ):
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard alerts"
        )
    if (
        not isinstance(raw_activity, list)
        or len(raw_activity) > UI_DASHBOARD_MAX_ACTIVITY
    ):
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard activity"
        )
    sources = value.get("sources")
    if not isinstance(sources, dict):
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard sources"
        )
    audit_total = _bounded_nonnegative_int(
        value.get("audit_total_24h"), field="audit_total_24h"
    )
    audit_failed = _bounded_nonnegative_int(
        value.get("audit_failed_24h"), field="audit_failed_24h"
    )
    if audit_failed > audit_total:
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard Audit counts"
        )
    system_source = _snapshot_text(
        sources.get("system"),
        field="system source",
        max_bytes=32,
        allow_empty=False,
    )
    audit_source = _snapshot_text(
        sources.get("audit"),
        field="audit source",
        max_bytes=32,
        allow_empty=False,
    )
    if system_source not in {"ok", "degraded"} or audit_source not in {
        "ok",
        "degraded",
    }:
        raise RuntimeError(
            f"Machine {machine} returned malformed dashboard source states"
        )
    return {
        "machine": machine,
        "remote": machine != "local",
        "generated_at": _finite_number(
            value.get("generated_at"), field="generated_at", minimum=0.0
        )
        or 0.0,
        "health": health,
        "version": _normalize_version(value.get("version")),
        "system": _normalize_system(value.get("system")),
        "alerts": [_normalize_alert(machine, item) for item in raw_alerts],
        "activity": [
            _normalize_activity(machine, item) for item in raw_activity
        ],
        "audit_total_24h": audit_total,
        "audit_failed_24h": audit_failed,
        "sources": {"system": system_source, "audit": audit_source},
    }


async def _snapshot(machine: str) -> dict[str, Any]:
    if machine == "local":
        value = await asyncio.to_thread(dashboard_snapshot)
    else:
        value = await _remote_dashboard_call(machine)
    return _normalize_snapshot(machine, value)


async def api_dashboard(request: Request) -> Response:
    """Return one process-scoped Dashboard snapshot for the selected machine."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        required = [SCOPE_SHELL_READ]
        if machine != "local":
            required.append(SCOPE_REMOTE_USE)
        _require_scopes(*required)
        return _json_ok(await _snapshot(machine))
    except HTTPException:
        raise
    except ValueError as exc:
        return _json_error(exc, status_code=404)
    except ConnectionError as exc:
        return _json_error(exc, status_code=503)
    except RuntimeError as exc:
        return _json_error(exc, status_code=502)
    except Exception as exc:
        return _json_error(exc)
