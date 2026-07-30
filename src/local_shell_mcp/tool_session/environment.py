"""Bounded runtime and capability orientation for explicit agent sessions."""

import importlib.metadata as importlib_metadata
import os
import platform
import re
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .. import __version__
from ..config.settings import Settings
from ..remote_worker.runtime import current_runtime_identity
from ..schemas.result_models.session import (
    SessionCapabilitiesEnvironment,
    SessionEnvironment,
    SessionPolicyEnvironment,
    SessionRuntimeEnvironment,
    SessionToolProbe,
    SessionToolsEnvironment,
    SessionWorkerRuntime,
    SessionWorkspaceEnvironment,
)
from ..terminal.conpty import is_available as conpty_available
from ..terminal.tmux import resolve_tmux
from ..ui.contracts import TUI_EXECUTABLE_NAME
from ..version import package_version

_REMOTE_WORKER_RUNTIME_ENV = "LOCAL_SHELL_MCP_REMOTE_WORKER_RUNTIME"
_WORKER_MANAGED_ENV = "LOCAL_SHELL_MCP_WORKER_MANAGED"

_PROBE_TIMEOUT_S = 1.5
_CACHE_TTL_S = 5.0
_VERSION_RE = re.compile(
    r"(?<![0-9])([0-9]+(?:\.[0-9]+){1,3}(?:[-+._]?[A-Za-z0-9]+)*)"
)
_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._+-]+")
_CACHE_LOCK = threading.Lock()
_TOOL_CACHE: dict[
    tuple[object, ...], tuple[float, SessionToolsEnvironment]
] = {}


@dataclass(frozen=True)
class _CommandProbe:
    name: str
    command: tuple[str, ...] | None
    source: str | None


def clear_session_environment_cache() -> None:
    """Clear briefly cached machine-static tool probes."""
    with _CACHE_LOCK:
        _TOOL_CACHE.clear()


def _safe_token(value: str, fallback: str, maximum: int = 80) -> str:
    normalized = _SAFE_TOKEN_RE.sub("_", value.strip())[:maximum].strip("_")
    return normalized or fallback


def _normalized_os(system: str) -> str:
    lowered = system.strip().lower()
    if lowered == "darwin":
        return "macos"
    if lowered.startswith("win"):
        return "windows"
    return _safe_token(lowered, "unknown")


def _resolve_command(value: str) -> tuple[str, ...] | None:
    try:
        parts = shlex.split(value, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    executable = parts[0]
    path = Path(executable).expanduser()
    resolved = str(path) if path.is_file() else shutil.which(executable)
    if not resolved:
        return None
    return (resolved, *parts[1:])


def _version_command(command: tuple[str, ...], kind: str) -> tuple[str, ...]:
    executable_name = Path(command[0]).name.lower()
    if kind == "shell" and executable_name in {"cmd", "cmd.exe"}:
        return (*command, "/d", "/c", "ver")
    if kind == "tmux":
        return (*command, "-V")
    if kind == "shell" and executable_name in {
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
    }:
        return (
            *command,
            "-NoLogo",
            "-NoProfile",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        )
    return (*command, "--version")


def _extract_version(output: str) -> str | None:
    match = _VERSION_RE.search(output[:4096])
    return match.group(1)[:80] if match else None


def _probe_command(spec: _CommandProbe) -> SessionToolProbe:
    if spec.command is None:
        return SessionToolProbe(
            available=False,
            status="missing",
            source=spec.source,
        )
    try:
        result = subprocess.run(  # noqa: S603
            list(_version_command(spec.command, spec.name)),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return SessionToolProbe(
            available=False,
            status="timeout",
            source=spec.source,
        )
    except OSError:
        return SessionToolProbe(
            available=False,
            status="error",
            source=spec.source,
        )
    output = f"{result.stdout[:2048]}\n{result.stderr[:2048]}"
    return SessionToolProbe(
        available=result.returncode == 0,
        status="available" if result.returncode == 0 else "error",
        version=_extract_version(output),
        source=spec.source,
    )


def _distribution_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def _chromium_command(playwright_version: str | None) -> tuple[str, ...] | None:
    candidates = (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "msedge",
        "microsoft-edge",
        "chrome",
    )
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return (path,)
    if playwright_version is None:
        return None
    script = (
        "from pathlib import Path; "
        "from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); "
        "path=p.chromium.executable_path; p.stop(); "
        "raise SystemExit(0 if Path(path).is_file() else 1)"
    )
    return (sys.executable, "-c", script)


def _opentui_probe(settings: Settings) -> SessionToolProbe:
    if settings.ui_tui_command:
        return SessionToolProbe(
            available=True,
            status="available",
            source="configured",
        )
    repository_root = Path(__file__).resolve().parents[2]
    candidates = (
        Path(sys.executable).resolve().parent / TUI_EXECUTABLE_NAME,
        Path(sys.argv[0]).resolve().parent / TUI_EXECUTABLE_NAME,
        repository_root / "ui-opentui" / "dist" / TUI_EXECUTABLE_NAME,
        Path.cwd() / "ui-opentui" / "dist" / TUI_EXECUTABLE_NAME,
        Path("/app/ui-opentui/dist") / TUI_EXECUTABLE_NAME,
    )
    if any(candidate.is_file() for candidate in candidates) or shutil.which(
        TUI_EXECUTABLE_NAME
    ):
        return SessionToolProbe(
            available=True,
            status="available",
            source="sidecar",
        )
    embedded = (
        Path(__file__).resolve().parents[1]
        / "ui_runtime"
        / f"{TUI_EXECUTABLE_NAME}.gz"
    )
    if embedded.is_file():
        return SessionToolProbe(
            available=True,
            status="available",
            version=package_version(),
            source="embedded",
        )
    source_candidates = (
        repository_root / "ui-opentui" / "src" / "tui.tsx",
        Path.cwd() / "ui-opentui" / "src" / "tui.tsx",
        Path("/app/ui-opentui/src/tui.tsx"),
    )
    if any(
        candidate.is_file() for candidate in source_candidates
    ) and shutil.which("bun"):
        return SessionToolProbe(
            available=True,
            status="available",
            source="source",
        )
    return SessionToolProbe(available=False, status="missing")


def _tool_probe_context(
    settings: Settings,
) -> tuple[
    tuple[object, ...],
    tuple[_CommandProbe, ...],
    str | None,
    SessionToolProbe,
]:
    shell = _resolve_command(settings.shell_executable)
    git = _resolve_command(settings.git_bin)
    ripgrep = _resolve_command(settings.rg_bin)
    tmux = resolve_tmux(settings.tmux_bin)
    curl = _resolve_command("curl")
    bun = _resolve_command("bun")
    playwright_version = _distribution_version("playwright")
    chromium = _chromium_command(playwright_version)
    opentui = _opentui_probe(settings)
    probes = (
        _CommandProbe("shell", shell, "configured"),
        _CommandProbe("git", git, "configured"),
        _CommandProbe("ripgrep", ripgrep, "configured"),
        _CommandProbe(
            "tmux",
            (tmux.path,) if tmux.path else None,
            tmux.source,
        ),
        _CommandProbe("curl", curl, "system"),
        _CommandProbe("bun", bun, "system"),
        _CommandProbe(
            "chromium",
            chromium,
            "system"
            if chromium and chromium[0] != sys.executable
            else "playwright",
        ),
    )
    key: tuple[object, ...] = (
        os.name,
        *(probe.command for probe in probes),
        *(probe.source for probe in probes),
        playwright_version,
        opentui.available,
        opentui.source,
        opentui.version,
    )
    return key, probes, playwright_version, opentui


def _collect_tools(settings: Settings) -> SessionToolsEnvironment:
    key, probes, playwright_version, opentui = _tool_probe_context(settings)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _TOOL_CACHE.get(key)
        if cached is not None and now - cached[0] <= _CACHE_TTL_S:
            return cached[1].model_copy(deep=True)

    results: dict[str, SessionToolProbe] = {}
    with ThreadPoolExecutor(max_workers=len(probes)) as executor:
        futures = {
            executor.submit(_probe_command, probe): probe.name
            for probe in probes
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                results[name] = SessionToolProbe(
                    available=False,
                    status="error",
                )

    tools = SessionToolsEnvironment(
        shell=results["shell"],
        git=results["git"],
        ripgrep=results["ripgrep"],
        tmux=results["tmux"],
        curl=results["curl"],
        bun=results["bun"],
        chromium=results["chromium"],
        playwright=SessionToolProbe(
            available=playwright_version is not None,
            status="available" if playwright_version is not None else "missing",
            version=playwright_version,
            source="python",
        ),
        opentui=opentui,
    )
    with _CACHE_LOCK:
        _TOOL_CACHE.clear()
        _TOOL_CACHE[key] = (now, tools.model_copy(deep=True))
    return tools


def _worker_runtime() -> SessionWorkerRuntime:
    active = os.getenv(_REMOTE_WORKER_RUNTIME_ENV) == "1"
    if not active:
        return SessionWorkerRuntime(
            active=False,
            service_kind="none",
            service_status="not_applicable",
        )
    identity = current_runtime_identity()
    managed = os.getenv(_WORKER_MANAGED_ENV) == "1"
    service_kind: Literal[
        "none", "manual", "systemd", "launchd", "windows_startup", "managed"
    ]
    if managed:
        system = _normalized_os(platform.system())
        match system:
            case "linux":
                service_kind = "systemd"
            case "macos":
                service_kind = "launchd"
            case "windows":
                service_kind = "windows_startup"
            case _:
                service_kind = "managed"
    else:
        service_kind = "manual"
    return SessionWorkerRuntime(
        active=True,
        worker_version=package_version(),
        bundle_version=str(identity.get("bundle_version") or "") or None,
        service_kind=service_kind,
        service_status="running",
    )


def _runtime_environment() -> SessionRuntimeEnvironment:
    return SessionRuntimeEnvironment(
        local_shell_mcp_version=__version__,
        package_version=package_version(),
        python_implementation=_safe_token(
            platform.python_implementation(), "unknown"
        ),
        python_version=platform.python_version()[:80],
        runtime_kind="frozen" if getattr(sys, "frozen", False) else "source",
        os=_normalized_os(platform.system()),
        release=_safe_token(platform.release(), "unknown"),
        architecture=_safe_token(platform.machine(), "unknown"),
        process_bits=64 if struct.calcsize("P") * 8 >= 64 else 32,
    )


def _agent_oauth_counts(
    settings: Settings, *, worker_active: bool
) -> tuple[int, int]:
    if worker_active or not settings.agent_bridge_enabled:
        return 0, 0
    try:
        from ..agent_bridge.auth import oauth_status
        from ..agent_bridge.auth_store import AgentAuthStore
        from ..agent_bridge.state import load_agent_manifest

        manifest = load_agent_manifest(settings.agent_config_dir)
        if manifest.status != "loaded":
            return 0, 0
        oauth_servers = [
            (name, server)
            for name, server in manifest.data.mcp_servers.items()
            if server.enabled and server.auth.mode == "oauth"
        ]
        if not oauth_servers:
            return 0, 0
        store = AgentAuthStore(settings.agent_auth_dir)
        authorized = sum(
            bool(oauth_status(store, name, server).get("authorized"))
            for name, server in oauth_servers
        )
        return len(oauth_servers), authorized
    except Exception:
        return 0, 0


def _policy_environment(settings: Settings) -> SessionPolicyEnvironment:
    return SessionPolicyEnvironment(
        server_mode=settings.mode,
        authentication_mode=settings.auth_mode,
        full_control=settings.allow_full_control,
        network_policy="tool_scoped",
        tool_timeout_s=settings.tool_timeout_s,
        shell_default_timeout_s=settings.run_shell_default_timeout_s,
        shell_max_timeout_s=settings.run_shell_max_timeout_s,
        max_output_bytes=settings.max_output_bytes,
        max_agent_sessions=settings.max_agent_sessions,
        agent_session_retention_s=settings.agent_session_retention_s,
        max_session_snapshots=settings.max_session_snapshots,
        max_session_snapshot_bytes=settings.max_session_snapshot_bytes,
        max_file_read_bytes=settings.max_file_read_bytes,
        max_file_write_bytes=settings.max_file_write_bytes,
        max_search_results=settings.max_grep_results,
        max_concurrent_commands=settings.max_concurrent_commands,
        max_persistent_shells=settings.max_tmux_sessions,
        max_http_request_bytes=settings.max_http_request_bytes,
        max_audit_event_bytes=settings.max_audit_event_bytes,
        max_transfer_archive_entries=settings.max_transfer_archive_entries,
        max_transfer_unpacked_bytes=settings.max_transfer_unpacked_bytes,
        remote_job_timeout_s=settings.remote_job_timeout_s,
        remote_max_pending_jobs=settings.remote_max_pending_jobs,
    )


def collect_session_environment(
    settings: Settings,
    *,
    workdir: str,
    target: Literal["local", "remote"],
    machine: str | None,
) -> SessionEnvironment:
    """Collect one bounded session environment without exposing private configuration."""
    try:
        tools = _collect_tools(settings)
    except Exception:
        unavailable = SessionToolProbe(available=False, status="error")
        tools = SessionToolsEnvironment(
            shell=unavailable,
            git=unavailable,
            ripgrep=unavailable,
            tmux=unavailable,
            curl=unavailable,
            bun=unavailable,
            chromium=unavailable,
            playwright=unavailable,
            opentui=unavailable,
        )
    worker_runtime = _worker_runtime()
    conpty = conpty_available()
    raw_pty = conpty or tools.tmux.available
    browser_ui = settings.ui_enabled and settings.mode in {"http", "both"}
    native_opentui = tools.opentui.available
    oauth_configured, oauth_authorized = _agent_oauth_counts(
        settings, worker_active=worker_runtime.active
    )
    return SessionEnvironment(
        runtime=_runtime_environment(),
        workspace=SessionWorkspaceEnvironment(
            workspace_root=str(settings.workspace_root.resolve()),
            workdir=workdir,
            target=target,
            machine=machine,
            worker_runtime=worker_runtime,
        ),
        tools=tools,
        capabilities=SessionCapabilitiesEnvironment(
            remote_worker=worker_runtime.active or settings.remote_enabled,
            raw_pty=raw_pty,
            conpty=conpty,
            browser_ui=browser_ui,
            native_opentui=native_opentui,
            browser_console=browser_ui and raw_pty,
            agent_bridge=settings.agent_bridge_enabled,
            oauth_mcp_clients=(
                settings.agent_bridge_enabled and not worker_runtime.active
            ),
            oauth_configured_mcp_servers=oauth_configured,
            oauth_authorized_mcp_servers=oauth_authorized,
            http_transfer=(
                settings.file_download_enabled
                and settings.mode in {"http", "both"}
            ),
            audit_full_payload=True,
        ),
        policy=_policy_environment(settings),
    )
