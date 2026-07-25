import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp.config.settings import Settings
from local_shell_mcp.schemas.result_models.session import SessionToolProbe
from local_shell_mcp.tool_session import environment as env_ops


def _settings(tmp_path: Path, **updates) -> Settings:
    values = {
        "workspace_root": tmp_path,
        "state_dir": tmp_path / "state",
        "mode": "both",
        "ui_enabled": True,
        "agent_bridge_enabled": True,
        "remote_enabled": True,
        "file_download_enabled": True,
    }
    values.update(updates)
    return Settings(**values)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Linux", "linux"), ("Darwin", "macos"), ("Windows", "windows")],
)
def test_normalized_os(value, expected):
    assert env_ops._normalized_os(value) == expected


def test_safe_tokens_and_versions_are_bounded_and_do_not_return_raw_text():
    assert (
        env_ops._safe_token(" Linux secret/path ", "unknown")
        == "Linux_secret_path"
    )
    assert (
        env_ops._extract_version("tool 12.3.4 private/path token") == "12.3.4"
    )
    assert env_ops._extract_version("no version here") is None


def test_version_command_handles_cmd_and_powershell():
    assert env_ops._version_command(("cmd.exe",), "shell")[-3:] == (
        "/d",
        "/c",
        "ver",
    )
    assert "$PSVersionTable" in " ".join(
        env_ops._version_command(("pwsh",), "shell")
    )
    assert env_ops._version_command(("git",), "git") == ("git", "--version")


def test_probe_command_reports_missing_timeout_error_and_version(monkeypatch):
    assert (
        env_ops._probe_command(
            env_ops._CommandProbe("git", None, "configured")
        ).status
        == "missing"
    )

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["tool"], 1)

    monkeypatch.setattr(env_ops.subprocess, "run", timeout)
    timed = env_ops._probe_command(
        env_ops._CommandProbe("git", ("git",), "configured")
    )
    assert timed.available is False and timed.status == "timeout"

    monkeypatch.setattr(
        env_ops.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    failed = env_ops._probe_command(
        env_ops._CommandProbe("git", ("git",), "configured")
    )
    assert failed.available is False and failed.status == "error"

    monkeypatch.setattr(
        env_ops.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="git version 2.51.0\nprivate/path", stderr=""
        ),
    )
    available = env_ops._probe_command(
        env_ops._CommandProbe("git", ("git",), "configured")
    )
    assert available.model_dump() == {
        "available": True,
        "status": "available",
        "version": "2.51.0",
        "source": "configured",
    }

    monkeypatch.setattr(
        env_ops.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="tool 1.2.3", stderr="failure secret"
        ),
    )
    errored = env_ops._probe_command(
        env_ops._CommandProbe("git", ("git",), "configured")
    )
    assert errored.status == "error"
    assert "secret" not in json.dumps(errored.model_dump())


def test_tool_collection_is_cached_and_probes_concurrently(
    monkeypatch, tmp_path
):
    settings = _settings(tmp_path)
    env_ops.clear_session_environment_cache()
    probes = tuple(
        env_ops._CommandProbe(name, (name,), "system")
        for name in (
            "shell",
            "git",
            "ripgrep",
            "tmux",
            "curl",
            "bun",
            "chromium",
        )
    )
    opentui = SessionToolProbe(available=False, status="missing")
    monkeypatch.setattr(
        env_ops,
        "_tool_probe_context",
        lambda _settings: (("cache-key",), probes, "1.61.0", opentui),
    )
    calls = []
    barrier = threading.Barrier(len(probes))

    def probe(spec):
        calls.append(spec.name)
        barrier.wait(timeout=1)
        return SessionToolProbe(
            available=True,
            status="available",
            version="1.2.3",
            source=spec.source,
        )

    monkeypatch.setattr(env_ops, "_probe_command", probe)
    first = env_ops._collect_tools(settings)
    second = env_ops._collect_tools(settings)

    assert sorted(calls) == sorted(probe.name for probe in probes)
    assert first.git.version == "1.2.3"
    assert second == first
    assert second is not first


def test_opentui_probe_configured_and_missing(monkeypatch, tmp_path):
    configured = _settings(tmp_path, ui_tui_command="trusted-tui")
    assert env_ops._opentui_probe(configured).source == "configured"

    monkeypatch.setattr(env_ops, "TUI_EXECUTABLE_NAME", "missing-tui-fixture")
    monkeypatch.setattr(env_ops.shutil, "which", lambda _name: None)
    missing = env_ops._opentui_probe(_settings(tmp_path))
    assert missing.available is False
    assert missing.status == "missing"


def test_worker_runtime_normalizes_manual_and_managed_services(monkeypatch):
    monkeypatch.delenv(env_ops._REMOTE_WORKER_RUNTIME_ENV, raising=False)
    assert env_ops._worker_runtime().service_status == "not_applicable"

    monkeypatch.setenv(env_ops._REMOTE_WORKER_RUNTIME_ENV, "1")
    monkeypatch.delenv(env_ops._WORKER_MANAGED_ENV, raising=False)
    monkeypatch.setattr(
        env_ops,
        "current_runtime_identity",
        lambda: {"bundle_version": "9.8.7", "sha256": "must-not-leak"},
    )
    manual = env_ops._worker_runtime()
    assert manual.active is True
    assert manual.service_kind == "manual"
    assert manual.bundle_version == "9.8.7"
    assert "must-not-leak" not in json.dumps(manual.model_dump())

    monkeypatch.setenv(env_ops._WORKER_MANAGED_ENV, "1")
    monkeypatch.setattr(env_ops.platform, "system", lambda: "Linux")
    assert env_ops._worker_runtime().service_kind == "systemd"
    monkeypatch.setattr(env_ops.platform, "system", lambda: "Darwin")
    assert env_ops._worker_runtime().service_kind == "launchd"
    monkeypatch.setattr(env_ops.platform, "system", lambda: "Windows")
    assert env_ops._worker_runtime().service_kind == "windows_startup"
    monkeypatch.setattr(env_ops.platform, "system", lambda: "Plan9")
    assert env_ops._worker_runtime().service_kind == "managed"


def test_runtime_environment_normalizes_source_and_frozen(monkeypatch):
    monkeypatch.setattr(env_ops.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(env_ops.platform, "release", lambda: "24.1 secret/path")
    monkeypatch.setattr(env_ops.platform, "machine", lambda: "arm64 private")
    monkeypatch.setattr(
        env_ops.platform, "python_implementation", lambda: "CPython"
    )
    monkeypatch.setattr(env_ops.platform, "python_version", lambda: "3.14.0")
    monkeypatch.setattr(env_ops.sys, "frozen", True, raising=False)

    runtime = env_ops._runtime_environment()
    assert runtime.runtime_kind == "frozen"
    assert runtime.os == "macos"
    assert runtime.release == "24.1_secret_path"
    assert runtime.architecture == "arm64_private"
    assert runtime.process_bits in {32, 64}


def test_collect_session_environment_is_allowlisted_and_falls_back(
    monkeypatch, tmp_path
):
    settings = _settings(
        tmp_path,
        oauth_admin_pin="private-pin-value",
        command_denylist=["private-command"],
        path_denylist=["private/path"],
    )
    tool = SessionToolProbe(available=True, status="available", version="1.0")
    tools = env_ops.SessionToolsEnvironment(
        shell=tool,
        git=tool,
        ripgrep=tool,
        tmux=tool,
        curl=tool,
        bun=tool,
        chromium=tool,
        playwright=tool,
        opentui=tool,
    )
    monkeypatch.setattr(env_ops, "_collect_tools", lambda _settings: tools)
    monkeypatch.setattr(env_ops, "conpty_available", lambda: False)
    monkeypatch.delenv(env_ops._REMOTE_WORKER_RUNTIME_ENV, raising=False)

    environment = env_ops.collect_session_environment(
        settings, workdir=str(tmp_path), target="local", machine=None
    )
    payload = json.dumps(environment.model_dump(mode="json"))
    assert environment.capabilities.raw_pty is True
    assert environment.capabilities.browser_console is True
    assert environment.policy.network_policy == "tool_scoped"
    for forbidden in (
        "private-pin-value",
        "private-command",
        "private/path",
        str(settings.state_dir),
        "oauth_admin_pin",
        "command_denylist",
        "path_denylist",
    ):
        assert forbidden not in payload

    monkeypatch.setattr(
        env_ops,
        "_collect_tools",
        lambda _settings: (_ for _ in ()).throw(
            RuntimeError("probe-secret-fixture")
        ),
    )
    fallback = env_ops.collect_session_environment(
        settings, workdir=str(tmp_path), target="local", machine=None
    )
    assert fallback.tools.git.status == "error"
    assert "probe-secret-fixture" not in json.dumps(
        fallback.model_dump(mode="json")
    )


def test_resolve_command_rejects_invalid_or_missing(monkeypatch):
    assert env_ops._resolve_command("'") is None
    monkeypatch.setattr(env_ops.shutil, "which", lambda _value: None)
    assert env_ops._resolve_command("missing-tool") is None


def test_agent_oauth_counts_reflect_private_authorization_without_names(
    tmp_path, monkeypatch
):
    from mcp.shared.auth import OAuthToken

    from local_shell_mcp.agent_bridge.auth_store import AgentAuthStore

    monkeypatch.delenv(env_ops._REMOTE_WORKER_RUNTIME_ENV, raising=False)
    monkeypatch.delenv(env_ops._WORKER_MANAGED_ENV, raising=False)
    settings = _settings(tmp_path)
    settings.agent_config_dir.mkdir(parents=True)
    (settings.agent_config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "private-server-name": {
                        "type": "http",
                        "url": "https://example.test/mcp",
                        "auth": {"mode": "oauth"},
                    },
                    "disabled": {
                        "type": "http",
                        "url": "https://disabled.test/mcp",
                        "enabled": False,
                        "auth": {"mode": "oauth"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    assert env_ops._agent_oauth_counts(settings, worker_active=False) == (1, 0)
    AgentAuthStore(settings.agent_auth_dir).set_tokens(
        "private-server-name",
        OAuthToken.model_validate(
            {"access_token": "fixture-access", "token_type": "Bearer"}
        ),
    )
    assert env_ops._agent_oauth_counts(settings, worker_active=False) == (1, 1)
    assert env_ops._agent_oauth_counts(settings, worker_active=True) == (0, 0)

    environment = env_ops.collect_session_environment(
        settings, workdir=str(tmp_path), target="local", machine=None
    )
    payload = json.dumps(environment.model_dump(mode="json"))
    assert environment.capabilities.oauth_configured_mcp_servers == 1
    assert environment.capabilities.oauth_authorized_mcp_servers == 1
    assert "private-server-name" not in payload
    assert "fixture-access" not in payload
