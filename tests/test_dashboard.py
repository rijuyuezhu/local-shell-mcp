from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import local_shell_mcp.dashboard as dashboard_module


@pytest.fixture(autouse=True)
def _reset_samples():
    original_cpu = dashboard_module._CPU_SAMPLE
    original_network = dashboard_module._NETWORK_SAMPLE
    dashboard_module._CPU_SAMPLE = None
    dashboard_module._NETWORK_SAMPLE = None
    yield
    dashboard_module._CPU_SAMPLE = original_cpu
    dashboard_module._NETWORK_SAMPLE = original_network


def test_percent_bounds_and_rejects_zero_total() -> None:
    assert dashboard_module._percent(5, 10) == 50.0
    assert dashboard_module._percent(-5, 10) == 0.0
    assert dashboard_module._percent(50, 10) == 100.0
    assert dashboard_module._percent(1, 0) is None


def test_local_system_snapshot_uses_interval_cpu_and_network_samples(
    monkeypatch, tmp_path: Path
) -> None:
    dashboard_module._CPU_SAMPLE = (100, 40)
    dashboard_module._NETWORK_SAMPLE = (10.0, 1_000, 2_000)
    monkeypatch.setattr(
        dashboard_module, "_read_linux_cpu_times", lambda: (200, 70)
    )
    monkeypatch.setattr(
        dashboard_module, "_read_linux_memory", lambda: (1_000, 500)
    )
    monkeypatch.setattr(
        dashboard_module, "_read_linux_network", lambda: (3_000, 5_000)
    )
    monkeypatch.setattr(dashboard_module.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(dashboard_module.time, "monotonic", lambda: 12.0)
    monkeypatch.setattr(dashboard_module.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        dashboard_module.os,
        "getloadavg",
        lambda: (2.0, 1.0, 0.5),
        raising=False,
    )
    monkeypatch.setattr(
        dashboard_module.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=10_000, used=4_000, free=6_000),
    )
    monkeypatch.setattr(
        dashboard_module,
        "get_settings",
        lambda: SimpleNamespace(workspace_root=tmp_path),
    )
    monkeypatch.setattr(
        dashboard_module.Path,
        "read_text",
        lambda self, encoding="utf-8": "123.5 0\n",
    )

    snapshot = dashboard_module.local_system_snapshot()

    assert snapshot["cpu_percent"] == 70.0
    assert snapshot["cpu_count"] == 8
    assert snapshot["memory_percent"] == 50.0
    assert snapshot["memory_used_bytes"] == 500
    assert snapshot["memory_total_bytes"] == 1_000
    assert snapshot["disk_percent"] == 40.0
    assert snapshot["network_rx_bps"] == 1_000.0
    assert snapshot["network_tx_bps"] == 1_500.0
    assert snapshot["load_1m"] == 2.0
    assert snapshot["uptime_s"] == 124


def test_local_system_snapshot_preserves_missing_metrics(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dashboard_module, "_read_linux_cpu_times", lambda: None)
    monkeypatch.setattr(dashboard_module, "_read_linux_memory", lambda: None)
    monkeypatch.setattr(dashboard_module, "_read_linux_network", lambda: None)
    monkeypatch.setattr(dashboard_module.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(
        dashboard_module.os,
        "getloadavg",
        lambda: (_ for _ in ()).throw(OSError("missing")),
        raising=False,
    )
    monkeypatch.setattr(
        dashboard_module.shutil,
        "disk_usage",
        lambda path: (_ for _ in ()).throw(OSError("missing")),
    )
    monkeypatch.setattr(
        dashboard_module,
        "get_settings",
        lambda: SimpleNamespace(workspace_root=tmp_path),
    )
    monkeypatch.setattr(
        dashboard_module.Path,
        "read_text",
        lambda self, encoding="utf-8": (_ for _ in ()).throw(
            OSError("missing")
        ),
    )

    snapshot = dashboard_module.local_system_snapshot()

    assert snapshot["cpu_percent"] is None
    assert snapshot["memory_percent"] is None
    assert snapshot["disk_percent"] is None
    assert snapshot["network_rx_bps"] is None
    assert snapshot["network_tx_bps"] is None
    assert snapshot["load_1m"] is None
    assert snapshot["uptime_s"] >= 0


def test_dashboard_snapshot_exposes_metadata_only_and_failure_alert(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        dashboard_module,
        "get_settings",
        lambda: SimpleNamespace(workspace_root=tmp_path),
    )
    monkeypatch.setattr(
        dashboard_module,
        "local_system_snapshot",
        lambda: {
            "timestamp": 20.0,
            "cpu_percent": 10.0,
            "cpu_count": 4,
            "memory_percent": 20.0,
            "memory_used_bytes": 200,
            "memory_total_bytes": 1_000,
            "disk_percent": 30.0,
            "disk_used_bytes": 300,
            "disk_total_bytes": 1_000,
            "load_1m": 0.5,
            "network_rx_bps": 12.0,
            "network_tx_bps": 8.0,
            "uptime_s": 100.0,
        },
    )
    monkeypatch.setattr(
        dashboard_module,
        "version_info",
        lambda: {
            "version": "9.9.9",
            "package_version": "9.9.9",
            "python": "3.14",
            "platform": "test-platform",
        },
    )
    monkeypatch.setattr(dashboard_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(
        dashboard_module,
        "query_audit",
        lambda **kwargs: {
            "entries": [
                {
                    "ts": 99.0,
                    "tool": "write_file",
                    "operation": "files",
                    "status": "failed",
                    "ok": False,
                    "paired": True,
                    "duration_ms": 5,
                    "input": {"path": "secret.txt", "content": "hidden"},
                    "output": {"content": "hidden"},
                    "error": {"message": "hidden"},
                },
                {
                    "ts": 98.0,
                    "tool": "read",
                    "operation": "files",
                    "status": "success",
                    "ok": True,
                    "paired": True,
                    "duration_ms": 2,
                },
            ],
            "count": 2,
            "total_matched": 7,
            "failed_matched": 4,
        },
    )

    snapshot = dashboard_module.dashboard_snapshot()

    assert snapshot["health"] == "attention"
    assert snapshot["version"]["version"] == "9.9.9"
    assert snapshot["audit_total_24h"] == 7
    assert snapshot["audit_failed_24h"] == 4
    assert snapshot["sources"] == {"system": "ok", "audit": "ok"}
    assert snapshot["alerts"][0]["title"] == "4 recent MCP call failure(s)"
    assert snapshot["activity"][0] == {
        "timestamp": 99.0,
        "kind": "failed",
        "title": "write_file",
        "detail": "files",
        "duration_ms": 5.0,
    }
    assert not ({"input", "output", "error"} & snapshot["activity"][0].keys())


def test_dashboard_snapshot_degrades_when_audit_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dashboard_module,
        "local_system_snapshot",
        lambda: {
            "timestamp": 20.0,
            "cpu_percent": None,
            "cpu_count": 1,
            "memory_percent": None,
            "memory_used_bytes": None,
            "memory_total_bytes": None,
            "disk_percent": None,
            "disk_used_bytes": None,
            "disk_total_bytes": None,
            "load_1m": None,
            "network_rx_bps": None,
            "network_tx_bps": None,
            "uptime_s": 10.0,
        },
    )
    monkeypatch.setattr(
        dashboard_module,
        "query_audit",
        lambda **kwargs: (_ for _ in ()).throw(
            OSError("audit store unavailable")
        ),
    )

    snapshot = dashboard_module.dashboard_snapshot()

    assert snapshot["health"] == "attention"
    assert snapshot["sources"]["audit"] == "degraded"
    assert snapshot["audit_total_24h"] == 0
    assert snapshot["activity"] == []
    assert snapshot["alerts"][0]["title"] == "Audit activity unavailable"
