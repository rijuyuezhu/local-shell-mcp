"""Append redacted, portable, bounded audit events to a private JSONL log."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import threading
import time
import uuid
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .agent_bridge.redaction import (
    SENSITIVE_FLAG_RE,
    SENSITIVE_KEY_RE,
    _redact_text,
    redact_configured_values,
)
from .config.settings import get_settings
from .utils.private_files import (
    append_private_bytes,
    atomic_write_private_bytes,
    private_file_lock,
)

DOWNLOAD_URL_TOKEN_RE = re.compile(
    r"(?P<prefix>(?:https?://[^\s/?#]+)?/download/)[A-Za-z0-9_-]+"
)

_AUDIT_THREAD_LOCK = threading.RLock()
_AUDIT_MAX_DEPTH = 12
_AUDIT_MAX_ITEMS = 200
_AUDIT_MAX_STRING_CHARS = 16_000
_AUDIT_PREVIEW_DEPTH = 4
_AUDIT_PREVIEW_ITEMS = 20
_AUDIT_PREVIEW_STRING_CHARS = 512
_AUDIT_TRUNCATED_KEY = "$local_shell_mcp_audit_truncated"
_AUDIT_BINARY_KEY = "$local_shell_mcp_audit_binary"
_AUDIT_CYCLE_KEY = "$local_shell_mcp_audit_cycle"
_AUDIT_SAFE_IDENTIFIER_SUFFIXES = ("_sha256", "_fingerprint", "_token_id")


def _audit_key_is_sensitive(name: str) -> bool:
    """Treat credential values as sensitive while retaining irreversible identifiers."""
    normalized = name.casefold()
    if normalized.endswith(_AUDIT_SAFE_IDENTIFIER_SUFFIXES):
        return False
    return bool(SENSITIVE_KEY_RE.search(name))


def _configured_secret_maps() -> tuple[dict[str, str], ...]:
    """Return configured secrets that must be removed wherever rendered."""
    settings = get_settings()
    secrets: dict[str, str] = {}
    if settings.oauth_admin_pin:
        secrets["oauth_admin_pin"] = settings.oauth_admin_pin
    return (secrets,) if secrets else ()


def _redact_download_urls(value: str) -> str:
    """Mask tokenized download URL path segments in audit text."""
    return DOWNLOAD_URL_TOKEN_RE.sub(r"\g<prefix><redacted>", value)


def _bounded_text(value: str, max_chars: int) -> str:
    """Redact one free-form string and bound its retained character count."""
    redacted = redact_configured_values(value, *_configured_secret_maps())
    redacted = _redact_download_urls(_redact_text(redacted))
    if len(redacted) <= max_chars:
        return redacted
    omitted = len(redacted) - max_chars
    return f"{redacted[:max_chars]}…<truncated {omitted} chars>"


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception as exc:
        return f"<{type(value).__name__} repr failed: {type(exc).__name__}>"


def _omitted_items(total: int | None, retained: int) -> dict[str, Any]:
    omitted = None if total is None else max(0, total - retained)
    return {
        _AUDIT_TRUNCATED_KEY: {
            "reason": "item_limit",
            "retained": retained,
            "omitted": omitted,
        }
    }


def _sanitize_audit_value(
    value: Any,
    *,
    field_name: str | None = None,
    depth: int = 0,
    seen: set[int] | None = None,
    max_depth: int = _AUDIT_MAX_DEPTH,
    max_items: int = _AUDIT_MAX_ITEMS,
    max_string_chars: int = _AUDIT_MAX_STRING_CHARS,
) -> Any:
    """Convert arbitrary values into redacted, portable, resource-bounded JSON data."""
    normalized_name = field_name or ""
    if normalized_name and _audit_key_is_sensitive(normalized_name):
        return "<redacted>"
    if depth > max_depth:
        return {
            _AUDIT_TRUNCATED_KEY: {
                "reason": "depth_limit",
                "max_depth": max_depth,
                "type": type(value).__name__,
            }
        }
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return (
            value
            if math.isfinite(value)
            else _bounded_text(repr(value), max_string_chars)
        )
    if isinstance(value, str):
        return _bounded_text(value, max_string_chars)
    if isinstance(value, bytes | bytearray | memoryview):
        data = bytes(value)
        return {
            _AUDIT_BINARY_KEY: {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        }
    if isinstance(value, Path):
        return _bounded_text(str(value), max_string_chars)
    if isinstance(value, Enum):
        return _sanitize_audit_value(
            value.value,
            field_name=field_name,
            depth=depth,
            seen=seen,
            max_depth=max_depth,
            max_items=max_items,
            max_string_chars=max_string_chars,
        )
    if isinstance(value, BaseModel):
        try:
            value = value.model_dump(mode="python", by_alias=True)
        except Exception:
            return _bounded_text(_safe_repr(value), max_string_chars)
    elif is_dataclass(value) and not isinstance(value, type):
        try:
            value = {
                item.name: getattr(value, item.name) for item in fields(value)
            }
        except Exception:
            return _bounded_text(_safe_repr(value), max_string_chars)

    if seen is None:
        seen = set()
    value_id = id(value)
    if isinstance(value, Mapping | list | tuple | set | frozenset):
        if value_id in seen:
            return {_AUDIT_CYCLE_KEY: type(value).__name__}
        seen.add(value_id)

    try:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            retained = 0
            try:
                total: int | None = len(value)
            except Exception:
                total = None
            for retained, (key, child) in enumerate(value.items()):
                if retained >= max_items:
                    result.update(_omitted_items(total, retained))
                    break
                key_text = _bounded_text(str(key), 256)
                if key_text in result:
                    key_text = f"{key_text}#{retained + 1}"
                result[key_text] = _sanitize_audit_value(
                    child,
                    field_name=str(key),
                    depth=depth + 1,
                    seen=seen,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_string_chars=max_string_chars,
                )
            return result

        if isinstance(value, list | tuple):
            result_list: list[Any] = []
            redact_next = False
            total = len(value)
            for child in value[:max_items]:
                if redact_next:
                    result_list.append("<redacted>")
                    redact_next = False
                    continue
                result_list.append(
                    _sanitize_audit_value(
                        child,
                        depth=depth + 1,
                        seen=seen,
                        max_depth=max_depth,
                        max_items=max_items,
                        max_string_chars=max_string_chars,
                    )
                )
                if isinstance(child, str) and SENSITIVE_FLAG_RE.fullmatch(
                    child
                ):
                    redact_next = True
            if total > max_items:
                result_list.append(_omitted_items(total, max_items))
            return result_list

        if isinstance(value, set | frozenset):
            ordered = sorted(value, key=_safe_repr)
            return _sanitize_audit_value(
                ordered,
                depth=depth,
                seen=seen,
                max_depth=max_depth,
                max_items=max_items,
                max_string_chars=max_string_chars,
            )

        return _bounded_text(_safe_repr(value), max_string_chars)
    finally:
        if isinstance(value, Mapping | list | tuple | set | frozenset):
            seen.discard(value_id)


def _preview_audit_value(value: Any) -> Any:
    """Return a compact already-redacted preview for an oversized event."""
    return _sanitize_audit_value(
        value,
        max_depth=_AUDIT_PREVIEW_DEPTH,
        max_items=_AUDIT_PREVIEW_ITEMS,
        max_string_chars=_AUDIT_PREVIEW_STRING_CHARS,
    )


def _encode_record(record: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _fit_record(record: dict[str, Any], max_bytes: int) -> bytes:
    """Fit one event inside its byte budget without dropping identity fields."""
    encoded = _encode_record(record)
    if len(encoded) <= max_bytes:
        return encoded

    original_bytes = len(encoded)
    identity_names = (
        "id",
        "ts",
        "event",
        "call_id",
        "transport",
        "tool",
        "ok",
        "duration_ms",
    )
    compact = {name: record[name] for name in identity_names if name in record}
    compact[_AUDIT_TRUNCATED_KEY] = {
        "reason": "event_byte_limit",
        "original_bytes": original_bytes,
        "max_bytes": max_bytes,
        "omitted_fields": [],
    }

    omitted: list[str] = []
    for name, value in record.items():
        if name in compact:
            continue
        candidate = {**compact, name: _preview_audit_value(value)}
        candidate[_AUDIT_TRUNCATED_KEY]["omitted_fields"] = omitted
        if len(_encode_record(candidate)) <= max_bytes:
            compact = candidate
        else:
            omitted.append(name)
    compact[_AUDIT_TRUNCATED_KEY]["omitted_fields"] = omitted
    encoded = _encode_record(compact)
    if len(encoded) <= max_bytes:
        return encoded

    minimal = {
        name: compact[name]
        for name in ("id", "ts", "event", "call_id", "tool", "ok")
        if name in compact
    }
    minimal[_AUDIT_TRUNCATED_KEY] = {
        "reason": "event_byte_limit",
        "original_bytes": original_bytes,
        "max_bytes": max_bytes,
        "omitted_fields": sorted(set(record) - set(minimal)),
    }
    encoded = _encode_record(minimal)
    if len(encoded) <= max_bytes:
        return encoded

    fallback = {
        "id": str(record.get("id") or "")[:32],
        "ts": record.get("ts"),
        "event": _bounded_text(str(record.get("event") or "audit_event"), 64),
        _AUDIT_TRUNCATED_KEY: "event exceeded configured byte limit",
    }
    encoded = _encode_record(fallback)
    return encoded if len(encoded) <= max_bytes else b""


@contextmanager
def _audit_transaction(path: Path) -> Generator[None]:
    """Serialize log append and retention across threads and processes."""
    with (
        _AUDIT_THREAD_LOCK,
        private_file_lock(path.with_name(path.name + ".lock")),
    ):
        yield


def _retention_units(lines: list[bytes]) -> list[list[tuple[int, bytes]]]:
    """Group tool-call start/end records so retention never splits completed pairs."""
    units: list[list[tuple[int, bytes]]] = []
    call_units: dict[str, list[tuple[int, bytes]]] = {}
    for index, raw_line in enumerate(lines):
        call_id = ""
        with contextlib.suppress(json.JSONDecodeError, UnicodeDecodeError):
            record = json.loads(raw_line)
            if isinstance(record, dict) and record.get("event") in {
                "tool_call_start",
                "tool_call_end",
            }:
                call_id = str(record.get("call_id") or "")
        if call_id:
            unit = call_units.get(call_id)
            if unit is None:
                unit = []
                call_units[call_id] = unit
                units.append(unit)
            unit.append((index, raw_line))
        else:
            units.append([(index, raw_line)])
    units.sort(key=lambda unit: max(item[0] for item in unit))
    return units


def _enforce_audit_log_limit(path: Path, max_bytes: int) -> None:
    """Atomically retain recent complete records within the configured log budget."""
    if max_bytes <= 0 or not path.exists() or path.stat().st_size <= max_bytes:
        return
    lines = path.read_bytes().splitlines(keepends=True)
    target_bytes = max(1, max_bytes // 2)
    selected: list[tuple[int, bytes]] = []
    selected_bytes = 0
    for unit in reversed(_retention_units(lines)):
        unit_bytes = sum(len(raw_line) for _, raw_line in unit)
        if unit_bytes > max_bytes:
            continue
        if selected and selected_bytes + unit_bytes > target_bytes:
            break
        selected.extend(unit)
        selected_bytes += unit_bytes
        if selected_bytes >= target_bytes:
            break
    selected.sort(key=lambda item: item[0])
    atomic_write_private_bytes(path, b"".join(line for _, line in selected))


def audit(event: str, **fields: Any) -> None:
    """Append one uniformly redacted, bounded, private audit record."""
    settings = get_settings()
    event_limit = max(512, int(settings.max_audit_event_bytes))
    if settings.max_audit_log_bytes > 0:
        event_limit = min(
            event_limit, max(512, int(settings.max_audit_log_bytes))
        )
    record = {
        "id": uuid.uuid4().hex,
        "ts": time.time(),
        "event": _bounded_text(str(event), 256),
        **{
            str(name): _sanitize_audit_value(value, field_name=str(name))
            for name, value in fields.items()
        },
    }
    encoded = _fit_record(record, event_limit)
    if not encoded:
        raise RuntimeError(
            "Audit event byte limit is too small to retain event identity"
        )

    path: Path = settings.audit_log_path
    with _audit_transaction(path):
        append_private_bytes(path, encoded)
        _enforce_audit_log_limit(path, settings.max_audit_log_bytes)


def new_audit_call_id() -> str:
    """Return a unique identifier used to link start/end audit records for one operation."""
    return uuid.uuid4().hex


def audit_tool_call_start(
    *,
    call_id: str,
    transport: str,
    tool: str,
    input: Any,
) -> None:
    """Record the bounded input and caller context for one tool call."""
    audit(
        "tool_call_start",
        call_id=call_id,
        transport=transport,
        tool=tool,
        input=input,
    )


def audit_tool_call_end(
    *,
    call_id: str,
    transport: str,
    tool: str,
    ok: bool,
    duration_ms: int,
    output: Any = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Record the bounded output or nested exception details for one tool call."""
    fields: dict[str, Any] = {
        "call_id": call_id,
        "transport": transport,
        "tool": tool,
        "ok": ok,
        "duration_ms": duration_ms,
    }
    if error is not None:
        fields["error"] = error
    else:
        fields["output"] = output
    audit("tool_call_end", **fields)
