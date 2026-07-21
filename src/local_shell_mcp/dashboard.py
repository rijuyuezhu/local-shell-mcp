"""Process-scoped system telemetry and safe Dashboard summaries."""

from __future__ import annotations

import contextlib
import math
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .audit import query_audit
from .config.settings import get_settings
from .version import version_info

_PROCESS_STARTED_AT = time.time()
_SYSTEM_SAMPLE_LOCK = threading.Lock()
_CPU_SAMPLE: tuple[int, int] | None = None
_NETWORK_SAMPLE: tuple[float, int, int] | None = None
_DASHBOARD_AUDIT_LIMIT = 160
_DASHBOARD_WINDOW_S = 86_400
_DASHBOARD_MAX_ALERTS = 12
_DASHBOARD_MAX_ACTIVITY = 12


def _read_linux_cpu_times() -> tuple[int, int] | None:
    """Return cumulative Linux CPU total and idle ticks when available."""
    try:
        fields = (
            Path("/proc/stat")
            .read_text(encoding="utf-8")
            .splitlines()[0]
            .split()
        )
        if not fields or fields[0] != "cpu":
            return None
        values = [int(value) for value in fields[1:]]
    except OSError, ValueError, IndexError:
        return None
    if len(values) < 4:
        return None
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _read_linux_memory() -> tuple[int, int] | None:
    """Return Linux memory total and used bytes when available."""
    try:
        values: dict[str, int] = {}
        for line in (
            Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
        ):
            name, separator, raw = line.partition(":")
            if not separator:
                continue
            token = raw.strip().split()[0]
            values[name] = int(token) * 1024
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree", 0))
    except OSError, ValueError, KeyError, IndexError:
        return None
    return total, max(0, total - available)


def _read_linux_network() -> tuple[int, int] | None:
    """Return aggregate non-loopback Linux network RX/TX bytes."""
    try:
        lines = (
            Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
        )
    except OSError, IndexError:
        return None
    received = transmitted = 0
    found = False
    for line in lines:
        interface, separator, raw = line.partition(":")
        if not separator or interface.strip() == "lo":
            continue
        fields = raw.split()
        if len(fields) < 9:
            continue
        try:
            received += int(fields[0])
            transmitted += int(fields[8])
        except ValueError:
            continue
        found = True
    return (received, transmitted) if found else None


def _percent(used: int | float, total: int | float) -> float | None:
    """Return one bounded percentage, or None for an unusable total."""
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, float(used) * 100.0 / float(total))), 1)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def local_system_snapshot() -> dict[str, Any]:
    """Collect a portable, best-effort process and host resource snapshot."""
    global _CPU_SAMPLE, _NETWORK_SAMPLE

    now = time.time()
    monotonic_now = time.monotonic()
    load_1m: float | None = None
    with contextlib.suppress(OSError, AttributeError):
        load_1m = round(float(os.getloadavg()[0]), 2)

    cpu_times = _read_linux_cpu_times()
    cpu_percent: float | None = None
    network = _read_linux_network()
    network_rx_bps: float | None = None
    network_tx_bps: float | None = None
    with _SYSTEM_SAMPLE_LOCK:
        if cpu_times is not None:
            if _CPU_SAMPLE is not None:
                total_delta = cpu_times[0] - _CPU_SAMPLE[0]
                idle_delta = cpu_times[1] - _CPU_SAMPLE[1]
                if total_delta > 0:
                    cpu_percent = round(
                        max(
                            0.0,
                            min(
                                100.0,
                                (total_delta - idle_delta)
                                * 100.0
                                / total_delta,
                            ),
                        ),
                        1,
                    )
            _CPU_SAMPLE = cpu_times
        if network is not None:
            if _NETWORK_SAMPLE is not None:
                elapsed = monotonic_now - _NETWORK_SAMPLE[0]
                if elapsed > 0:
                    network_rx_bps = max(
                        0.0, (network[0] - _NETWORK_SAMPLE[1]) / elapsed
                    )
                    network_tx_bps = max(
                        0.0, (network[1] - _NETWORK_SAMPLE[2]) / elapsed
                    )
            _NETWORK_SAMPLE = (monotonic_now, network[0], network[1])

    cpu_count = max(1, os.cpu_count() or 1)
    if cpu_percent is None and load_1m is not None:
        cpu_percent = round(
            max(0.0, min(100.0, load_1m * 100.0 / cpu_count)), 1
        )

    memory = _read_linux_memory()
    memory_total = memory[0] if memory else None
    memory_used = memory[1] if memory else None
    try:
        disk = shutil.disk_usage(get_settings().workspace_root)
    except OSError:
        disk = None

    uptime_s = max(0.0, now - _PROCESS_STARTED_AT)
    with contextlib.suppress(OSError, ValueError, IndexError):
        uptime_s = float(
            Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
        )

    return {
        "timestamp": now,
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "memory_percent": (
            _percent(memory_used, memory_total)
            if memory_used is not None and memory_total is not None
            else None
        ),
        "memory_used_bytes": memory_used,
        "memory_total_bytes": memory_total,
        "disk_percent": _percent(disk.used, disk.total) if disk else None,
        "disk_used_bytes": disk.used if disk else None,
        "disk_total_bytes": disk.total if disk else None,
        "load_1m": load_1m,
        "network_rx_bps": (
            round(network_rx_bps, 1) if network_rx_bps is not None else None
        ),
        "network_tx_bps": (
            round(network_tx_bps, 1) if network_tx_bps is not None else None
        ),
        "uptime_s": round(max(0.0, uptime_s)),
    }


def _audit_failed(entry: dict[str, Any]) -> bool:
    return (
        entry.get("ok") is False or str(entry.get("status") or "") == "failed"
    )


def dashboard_activity(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return metadata-only recent activity suitable for a read-only dashboard."""
    rows: list[dict[str, Any]] = []
    for entry in entries[:_DASHBOARD_MAX_ACTIVITY]:
        status = str(entry.get("status") or "")
        running = entry.get("paired") is False or status in {
            "running",
            "unpaired",
        }
        rows.append(
            {
                "timestamp": _finite_number(entry.get("ts")) or 0.0,
                "kind": "failed"
                if _audit_failed(entry)
                else "running"
                if running
                else "success",
                "title": str(
                    entry.get("tool") or entry.get("event") or "MCP activity"
                ),
                "detail": str(entry.get("operation") or "other"),
                "duration_ms": _finite_number(entry.get("duration_ms")),
            }
        )
    return rows


def dashboard_alerts(
    system: dict[str, Any],
    entries: list[dict[str, Any]],
    source_alerts: list[dict[str, Any]] | None = None,
    *,
    failed_count: int | None = None,
) -> list[dict[str, Any]]:
    """Build severity-ordered alerts without exposing Audit payloads."""
    alerts: list[dict[str, Any]] = list(source_alerts or [])
    for field, label, warning, critical in (
        ("disk_percent", "Workspace disk", 85.0, 95.0),
        ("memory_percent", "Memory", 90.0, 98.0),
    ):
        percent = _finite_number(system.get(field))
        if percent is None or percent < warning:
            continue
        alerts.append(
            {
                "severity": "critical" if percent >= critical else "warning",
                "title": f"{label} is {percent:.0f}% full",
                "detail": (
                    str(get_settings().workspace_root)
                    if field == "disk_percent"
                    else "Host memory pressure is elevated"
                ),
            }
        )

    effective_failed_count = (
        sum(_audit_failed(entry) for entry in entries)
        if failed_count is None
        else max(0, failed_count)
    )
    if effective_failed_count:
        alerts.append(
            {
                "severity": "warning",
                "title": f"{effective_failed_count} recent MCP call failure(s)",
                "detail": "Open Audit for authorized call details",
            }
        )

    severity_rank = {"info": 0, "warning": 1, "critical": 2}
    alerts.sort(
        key=lambda alert: severity_rank.get(str(alert.get("severity")), 0),
        reverse=True,
    )
    return alerts[:_DASHBOARD_MAX_ALERTS]


def dashboard_snapshot() -> dict[str, Any]:
    """Return one process-scoped system and Audit telemetry snapshot."""
    system = local_system_snapshot()
    source_alerts: list[dict[str, Any]] = []
    try:
        audit_payload = query_audit(
            limit=_DASHBOARD_AUDIT_LIMIT,
            start_ts=time.time() - _DASHBOARD_WINDOW_S,
            sort="desc",
        )
    except Exception as exc:
        audit_payload = {"entries": [], "count": 0, "total_matched": 0}
        source_alerts.append(
            {
                "severity": "warning",
                "title": "Audit activity unavailable",
                "detail": type(exc).__name__,
            }
        )

    raw_entries = audit_payload.get("entries")
    entries = (
        [entry for entry in raw_entries if isinstance(entry, dict)]
        if isinstance(raw_entries, list)
        else []
    )
    total_matched = audit_payload.get("total_matched", len(entries))
    if (
        isinstance(total_matched, bool)
        or not isinstance(total_matched, int)
        or total_matched < 0
    ):
        total_matched = len(entries)
    failed_count = audit_payload.get(
        "failed_matched", sum(_audit_failed(entry) for entry in entries)
    )
    if (
        isinstance(failed_count, bool)
        or not isinstance(failed_count, int)
        or failed_count < 0
        or failed_count > total_matched
    ):
        failed_count = sum(_audit_failed(entry) for entry in entries)
    alerts = dashboard_alerts(
        system,
        entries,
        source_alerts,
        failed_count=failed_count,
    )
    highest = str(alerts[0].get("severity") or "") if alerts else ""
    health = (
        "critical"
        if highest == "critical"
        else "attention"
        if alerts
        else "healthy"
    )

    return {
        "generated_at": time.time(),
        "health": health,
        "version": version_info(),
        "system": system,
        "alerts": alerts,
        "activity": dashboard_activity(entries),
        "audit_total_24h": total_matched,
        "audit_failed_24h": failed_count,
        "sources": {
            "system": "ok",
            "audit": "degraded" if source_alerts else "ok",
        },
    }
