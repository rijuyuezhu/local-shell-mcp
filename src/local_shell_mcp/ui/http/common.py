"""Shared stateless validation and response helpers for Human UI adapters."""

from collections.abc import Callable
from typing import Any

from starlette.responses import JSONResponse

from ...config.settings import get_settings
from ...remote.manager import remote_manager


def json_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    """Return the common Human UI exception envelope."""
    return JSONResponse(
        {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        },
        status_code=status_code,
    )


def bounded_text(
    value: Any,
    *,
    field: str,
    max_bytes: int,
    default: str = "",
    allow_empty: bool = True,
) -> str:
    """Normalize stripped text and enforce its encoded byte limit."""
    normalized = str(value if value is not None else default).strip()
    if not normalized and not allow_empty:
        raise ValueError(f"{field} is required")
    if len(normalized.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} encoded bytes")
    return normalized


def bounded_int(
    value: Any,
    *,
    field: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Normalize an integer and enforce an inclusive range."""
    if value in {None, ""}:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return normalized


def sorted_entry_payloads(
    entries: list[Any],
    payload_factory: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert file entries to UI payloads and sort directories first."""
    rows = [payload_factory(entry) for entry in entries]
    rows.sort(
        key=lambda item: (
            0 if item["type"] == "dir" else 1,
            str(item["name"]).casefold(),
            str(item["name"]),
        )
    )
    return rows


def require_remote_machine(machine: str) -> None:
    """Require one configured remote worker to exist and be online."""
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
