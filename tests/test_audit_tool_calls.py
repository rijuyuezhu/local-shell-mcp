import json

import pytest
from fastapi.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.server.mcp.app import build_mcp
from tests.helpers import mcp_text


def _audit_records(path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _tool_call_pairs(records, tool_name):
    starts = [
        r
        for r in records
        if r.get("event") == "tool_call_start" and r.get("tool") == tool_name
    ]
    ends = [
        r
        for r in records
        if r.get("event") == "tool_call_end" and r.get("tool") == tool_name
    ]
    return starts, ends


def test_http_tool_calls_audit_full_input_output_and_auth_context(
    tmp_path, monkeypatch
):
    (tmp_path / "alpha.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH",
        str(tmp_path / ".local-shell-mcp" / "audit.jsonl"),
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = TestClient(build_http_app()).post(
        "/tools/read_file", json={"path": "alpha.txt"}
    )

    assert response.status_code == 200
    records = _audit_records(get_settings().audit_log_path)
    starts, ends = _tool_call_pairs(records, "read_file")

    assert len(starts) == 1
    assert len(ends) == 1
    assert starts[0]["call_id"] == ends[0]["call_id"]
    assert starts[0]["transport"] == "http"
    assert starts[0]["input"] == {"path": "alpha.txt"}
    assert ends[0]["ok"] is True
    assert ends[0]["output"] == response.json()
    assert ends[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_mcp_tool_calls_audit_full_input_output(tmp_path, monkeypatch):
    (tmp_path / "beta.txt").write_text("world", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH",
        str(tmp_path / ".local-shell-mcp" / "audit.jsonl"),
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = await build_mcp().call_tool("read_file", {"path": "beta.txt"})
    payload = json.loads(mcp_text(response))

    records = _audit_records(get_settings().audit_log_path)
    starts, ends = _tool_call_pairs(records, "read_file")

    assert len(starts) == 1
    assert len(ends) == 1
    assert starts[0]["call_id"] == ends[0]["call_id"]
    assert starts[0]["transport"] == "mcp"
    assert starts[0]["input"]["path"] == "beta.txt"
    assert starts[0]["input"]["binary_preview_bytes"] == 256
    assert ends[0]["ok"] is True
    assert ends[0]["output"] == payload


@pytest.mark.asyncio
async def test_mcp_tool_structured_errors_are_audited_with_input_and_output(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH",
        str(tmp_path / ".local-shell-mcp" / "audit.jsonl"),
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = await build_mcp().call_tool("read_file", {"path": "missing.txt"})
    payload = json.loads(mcp_text(response))

    records = _audit_records(get_settings().audit_log_path)
    starts, ends = _tool_call_pairs(records, "read_file")

    assert len(starts) == 1
    assert len(ends) == 1
    assert starts[0]["input"]["path"] == "missing.txt"
    assert starts[0]["input"]["binary_preview_bytes"] == 256
    assert ends[0]["ok"] is True
    assert ends[0]["output"] == payload
    assert payload["ok"] is True
    assert payload["data"]["status"] == "not_found"
