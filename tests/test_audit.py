from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from local_shell_mcp.audit import (
    _AUDIT_BINARY_KEY,
    _AUDIT_CYCLE_KEY,
    _AUDIT_TRUNCATED_KEY,
    _coalesce_audit_records,
    audit,
    audit_tool_call_end,
    audit_tool_call_start,
    get_audit_entry,
    query_audit,
)
from local_shell_mcp.config.settings import clear_settings_cache, get_settings


def _configure_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_log_bytes: int = 20_000_000,
    max_event_bytes: int = 1_000_000,
) -> Path:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", str(max_log_bytes)
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_MAX_AUDIT_EVENT_BYTES", str(max_event_bytes)
    )
    clear_settings_cache()
    return get_settings().audit_log_path


def _records(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _audit_process(
    workspace: str, state_dir: str, worker: int, events: int
) -> None:
    os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] = workspace
    os.environ["LOCAL_SHELL_MCP_STATE_DIR"] = state_dir
    os.environ["LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES"] = "5000000"
    os.environ["LOCAL_SHELL_MCP_MAX_AUDIT_EVENT_BYTES"] = "100000"
    clear_settings_cache()
    for index in range(events):
        audit("process_event", worker=worker, index=index)


def test_audit_uniformly_redacts_secrets_but_retains_fingerprints(
    tmp_path, monkeypatch
):
    path = _configure_audit(tmp_path, monkeypatch)
    pin = "correct-horse-battery-staple"
    raw_token = "ghp_1234567890abcdef1234567890abcdef"
    fingerprint = "0123456789abcdef"
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", pin)
    clear_settings_cache()

    audit(
        "security_event",
        command=f"echo safe --api-key={raw_token} {pin}",
        headers={"Authorization": f"Bearer {raw_token}"},
        token=raw_token,
        token_sha256=fingerprint,
        token_fingerprint=fingerprint,
        url="https://files.test/download/sensitive-link-token",
        nested={"password": "hidden", "detail": f"Bearer {raw_token}"},
    )

    text = path.read_text(encoding="utf-8")
    record = _records(path)[0]
    assert raw_token not in text
    assert pin not in text
    assert "sensitive-link-token" not in text
    assert "/download/<redacted>" in text
    assert "echo safe" in record["command"]
    assert record["headers"]["Authorization"] == "<redacted>"
    assert record["token"] == "<redacted>"
    assert record["token_sha256"] == fingerprint
    assert record["token_fingerprint"] == fingerprint
    assert record["nested"]["password"] == "<redacted>"


def test_audit_values_are_portable_and_cycle_safe(tmp_path, monkeypatch):
    path = _configure_audit(tmp_path, monkeypatch)
    cycle: dict[str, Any] = {}
    cycle["self"] = cycle

    audit(
        "portable_event",
        payload={
            "cycle": cycle,
            "binary": b"\x00\xffpayload",
            "nan": float("nan"),
            "infinity": float("inf"),
            "path": tmp_path / "artifact.txt",
            "set": {"z", "a"},
            "object": object(),
        },
    )

    payload = _records(path)[0]["payload"]
    assert payload["cycle"]["self"] == {_AUDIT_CYCLE_KEY: "dict"}
    assert payload["binary"][_AUDIT_BINARY_KEY]["bytes"] == 9
    assert len(payload["binary"][_AUDIT_BINARY_KEY]["sha256"]) == 64
    assert payload["nan"] == "nan"
    assert payload["infinity"] == "inf"
    assert payload["path"].endswith("artifact.txt")
    assert payload["set"] == ["a", "z"]
    assert isinstance(payload["object"], str)


def test_audit_event_is_bounded_without_losing_identity(tmp_path, monkeypatch):
    path = _configure_audit(
        tmp_path,
        monkeypatch,
        max_log_bytes=10_000,
        max_event_bytes=1_200,
    )

    audit(
        "large_event",
        call_id="call-large",
        tool="read",
        payload={
            "large": "x" * 100_000,
            "items": list(range(1_000)),
        },
    )

    raw = path.read_bytes()
    record = json.loads(raw)
    assert len(raw) <= 1_200
    assert record["event"] == "large_event"
    assert record["call_id"] == "call-large"
    assert record["tool"] == "read"
    assert record[_AUDIT_TRUNCATED_KEY]["reason"] == "event_byte_limit"
    assert record[_AUDIT_TRUNCATED_KEY]["original_bytes"] > len(raw)


def test_audit_preserves_nested_error_details(tmp_path, monkeypatch):
    path = _configure_audit(tmp_path, monkeypatch)

    audit_tool_call_start(
        call_id="nested-error",
        transport="mcp",
        tool="read",
        input={"path": "missing.txt"},
    )
    audit_tool_call_end(
        call_id="nested-error",
        transport="mcp",
        tool="read",
        ok=False,
        duration_ms=5,
        error={
            "type": "OuterError",
            "message": "read failed",
            "cause": {
                "type": "FileNotFoundError",
                "message": "missing.txt",
                "context": {"attempt": 2},
            },
        },
    )

    start, end = _records(path)
    assert start["input"] == {"path": "missing.txt"}
    assert end["error"]["type"] == "OuterError"
    assert end["error"]["cause"] == {
        "type": "FileNotFoundError",
        "message": "missing.txt",
        "context": {"attempt": 2},
    }


def test_audit_threaded_appends_are_complete_and_private(tmp_path, monkeypatch):
    path = _configure_audit(tmp_path, monkeypatch)

    def append(index: int) -> None:
        audit("thread_event", index=index, payload=f"value-{index}")

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(append, range(200)))

    records = _records(path)
    assert len(records) == 200
    assert {record["index"] for record in records} == set(range(200))
    assert len({record["id"] for record in records}) == 200
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
        assert (
            path.with_name(path.name + ".lock").stat().st_mode & 0o777 == 0o600
        )


def test_audit_cross_process_appends_do_not_corrupt_jsonl(
    tmp_path, monkeypatch
):
    path = _configure_audit(tmp_path, monkeypatch)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_audit_process,
            args=(str(tmp_path), str(tmp_path / ".state"), worker, 25),
        )
        for worker in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    records = _records(path)
    assert len(records) == 100
    assert {(record["worker"], record["index"]) for record in records} == {
        (worker, index) for worker in range(4) for index in range(25)
    }


def test_audit_retention_keeps_completed_tool_calls_paired(
    tmp_path, monkeypatch
):
    path = _configure_audit(
        tmp_path,
        monkeypatch,
        max_log_bytes=3_000,
        max_event_bytes=1_000,
    )

    for index in range(20):
        call_id = f"call-{index}"
        audit_tool_call_start(
            call_id=call_id,
            transport="mcp",
            tool="read",
            input={"path": f"file-{index}.txt", "padding": "s" * 180},
        )
        audit_tool_call_end(
            call_id=call_id,
            transport="mcp",
            tool="read",
            ok=True,
            duration_ms=index,
            output={"content": "e" * 180},
        )

    records = _records(path)
    by_call: dict[str, set[str]] = {}
    for record in records:
        call_id = str(record.get("call_id") or "")
        if call_id:
            by_call.setdefault(call_id, set()).add(record["event"])

    assert path.stat().st_size <= 3_000
    assert by_call
    assert all(
        events == {"tool_call_start", "tool_call_end"}
        for events in by_call.values()
    )


def test_query_audit_pairs_calls_folds_children_and_hides_auth(
    tmp_path, monkeypatch
):
    _configure_audit(tmp_path, monkeypatch)
    audit(
        "tool_call_start",
        call_id="call-1",
        transport="mcp",
        tool="write_file",
        session_id="session-a",
        input={"path": "notes.txt", "content": "hello"},
    )
    audit(
        "file_link_created",
        parent_call_id="call-1",
        url="https://files.test/download/private-token",
    )
    audit(
        "tool_call_end",
        call_id="call-1",
        transport="mcp",
        tool="write_file",
        ok=True,
        duration_ms=7,
        output={"path": "notes.txt"},
    )
    audit("auth_ok", subject="browser")

    result = query_audit()

    assert result["count"] == 1
    assert result["total_matched"] == 1
    entry = result["entries"][0]
    assert entry["id"] == "call:call-1"
    assert entry["operation"] == "files"
    assert entry["session"] == "session-a"
    assert entry["status"] == "success"
    assert entry["paired"] is True
    assert entry["input"]["path"] == "notes.txt"
    assert entry["output"] == {"path": "notes.txt"}
    assert entry["related_events"][0]["event"] == "file_link_created"
    assert entry["related_events"][0]["url"].endswith("/download/<redacted>")
    assert "_source_indexes" not in entry
    assert get_audit_entry("call:call-1") == entry


def test_query_audit_filters_sorts_limits_and_skips_malformed_lines(
    tmp_path, monkeypatch
):
    path = _configure_audit(tmp_path, monkeypatch)
    audit(
        "tool_call_start",
        call_id="read-1",
        tool="read",
        transport="http",
        session_id="session-a",
        input={"path": "alpha.txt"},
    )
    audit(
        "tool_call_end",
        call_id="read-1",
        tool="read",
        transport="http",
        ok=True,
        duration_ms=2,
        output={"content": "alpha"},
    )
    audit("job_started", job_id="job-1", command="compile beta")
    with path.open("ab") as handle:
        handle.write(b"not-json\n")

    files = query_audit(operation="files", search="READ", sort="asc")
    jobs = query_audit(event="job", operation="jobs", limit=1)
    session = query_audit(session="SESSION-A")
    payload_only = query_audit(search="ALPHA")

    assert [entry["id"] for entry in files["entries"]] == ["call:read-1"]
    assert jobs["count"] == 1
    assert jobs["total_matched"] == 1
    assert jobs["entries"][0]["event"] == "job_started"
    assert session["count"] == 1
    assert session["entries"][0]["session"] == "session-a"
    assert payload_only["count"] == 0
    with pytest.raises(ValueError, match="sort must be asc or desc"):
        query_audit(sort="sideways")
    with pytest.raises(ValueError, match="start_ts"):
        query_audit(start_ts=2, end_ts=1)
    with pytest.raises(ValueError, match="Unknown audit entry"):
        get_audit_entry("missing")


def test_coalesce_audit_records_supports_legacy_calls_without_ids():
    rows = _coalesce_audit_records(
        [
            {
                "ts": 1.0,
                "event": "tool_call_start",
                "tool": "read",
                "session_id": "legacy-session",
                "input": {"path": "one.txt"},
            },
            {
                "ts": 2.0,
                "event": "tool_call_end",
                "tool": "read",
                "session_id": "legacy-session",
                "ok": False,
                "duration_ms": 3,
                "error": {"message": "missing"},
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "legacy-call:1.0:0"
    assert rows[0]["status"] == "failed"
    assert rows[0]["paired"] is True
    assert rows[0]["error"] == {"message": "missing"}
