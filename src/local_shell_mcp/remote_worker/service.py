"""Cross-platform user-service management for the remote worker."""

import contextlib
import hashlib
import json
import os
import platform
import plistlib
import posixpath
import re
import shutil
import subprocess
import sys
import time
from collections.abc import MutableMapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from ..utils.private_files import (
    atomic_write_private_bytes,
    atomic_write_private_text,
)
from . import runtime
from .profiles import read_worker_profile
from .state import (
    WORKER_PROFILE_ID_ENV,
    WORKER_RUNTIME_DIGEST_ENV,
    active_worker_runtime_digest,
    worker_profile_dir,
    worker_runtime_dir_for_digest,
)

_SERVICE_NAME = "local-shell-mcp-worker"
_LAUNCHD_LABEL = "com.fwerkor.local-shell-mcp-worker"
_WORKER_MANAGED_ENV = "LOCAL_SHELL_MCP_WORKER_MANAGED"
_LAUNCHD_PATH_SEPARATOR = ":"
_LAUNCHD_HOMEBREW_DIRS = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
)
_LAUNCHD_SYSTEM_DIRS = (
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)
_MAX_LOG_BYTES = 4 * 1024 * 1024
_MAX_LOG_LINES = 2_000

type ServiceManager = Literal["systemd", "launchd", "unsupported"]
type ServiceState = Literal[
    "unsupported",
    "unavailable",
    "not_installed",
    "stopped",
    "running",
    "failed",
    "unknown",
]


class WorkerServiceError(RuntimeError):
    """Raised when a supported user-service command fails."""


@dataclass(frozen=True)
class WorkerServiceStatus:
    """Stable JSON-serializable worker user-service status."""

    schema_version: int
    """Status schema version."""
    manager: ServiceManager
    """Detected native per-user service manager."""
    supported: bool
    """Whether this platform has an approved service implementation."""
    available: bool
    """Whether the native manager is reachable for the current user."""
    installed: bool
    """Whether the expected unit or plist is installed."""
    enabled: bool
    """Whether the service is configured for user-session startup."""
    running: bool
    """Whether the native manager reports an active worker process."""
    pid: int | None
    """Native manager process id when available."""
    state: ServiceState
    """Normalized service lifecycle state."""
    unit_path: str | None
    """Expected unit or plist path, excluding credential state."""
    log_path: str | None
    """Managed private log path when the manager uses a file."""

    def to_dict(self) -> dict[str, Any]:
        """Return the typed status as a plain JSON object."""
        return asdict(self)


@dataclass(frozen=True)
class WorkerServiceResult:
    """Stable JSON result returned by one lifecycle mutation."""

    schema_version: int
    """Result schema version."""
    action: str
    """Lifecycle action that produced the result."""
    changed: bool
    """Whether the requested lifecycle state changed."""
    status: WorkerServiceStatus
    """Truthful service status after the action."""

    def to_dict(self) -> dict[str, Any]:
        """Return the lifecycle result as a plain JSON object."""
        return {
            "schema_version": self.schema_version,
            "action": self.action,
            "changed": self.changed,
            "status": self.status.to_dict(),
        }


def _user_home() -> Path:
    configured = os.getenv("HOME") or os.getenv("USERPROFILE")
    return Path(configured).expanduser() if configured else Path.home()


def systemd_unit_path() -> Path:
    """Return the user systemd unit path."""
    return (
        _user_home()
        / ".config"
        / "systemd"
        / "user"
        / f"{_SERVICE_NAME}.service"
    )


def launchd_plist_path() -> Path:
    """Return the per-user launchd plist path."""
    return _user_home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def launcher_path() -> Path:
    """Return the stable private worker launcher path."""
    return runtime.worker_state_dir() / "bin" / "worker-launcher.py"


def launchd_log_path() -> Path:
    """Return the private combined launchd worker log path."""
    return runtime.worker_state_dir() / "service" / "worker.log"


def service_manager() -> ServiceManager:
    """Return the native user-service manager for this platform."""
    system = platform.system()
    if system == "Linux":
        return "systemd"
    if system == "Darwin":
        return "launchd"
    return "unsupported"


def _user_id() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else 0


def _launchd_domain() -> str:
    return f"gui/{_user_id()}"


def _launchd_target() -> str:
    return f"{_launchd_domain()}/{_LAUNCHD_LABEL}"


def _run(
    command: list[str],
    *,
    timeout: float = 15,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_checked(
    command: list[str],
    *,
    allowed_returncodes: set[int] | None = None,
    timeout: float = 15,
) -> subprocess.CompletedProcess[str]:
    allowed = {0} if allowed_returncodes is None else allowed_returncodes
    try:
        result = _run(command, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkerServiceError(
            f"worker service command failed: {type(exc).__name__}"
        ) from exc
    if result.returncode not in allowed:
        raise WorkerServiceError(
            f"worker service command exited with {result.returncode}"
        )
    return result


def _manager_executable(manager: ServiceManager) -> str | None:
    if manager == "systemd":
        return shutil.which("systemctl")
    if manager == "launchd":
        return shutil.which("launchctl")
    return None


def _launchd_session_path_entries() -> tuple[str, ...]:
    """Return sanitized absolute PATH entries exported by the GUI launchd domain."""
    if platform.system() != "Darwin":
        return ()
    executable = shutil.which("launchctl")
    if executable is None:
        return ()
    try:
        result = _run([executable, "getenv", "PATH"])
    except OSError, subprocess.SubprocessError:
        return ()
    if result.returncode:
        return ()
    entries = []
    for raw in result.stdout.split(_LAUNCHD_PATH_SEPARATOR):
        entry = raw.strip()
        if entry and posixpath.isabs(entry):
            entries.append(entry)
    return tuple(dict.fromkeys(entries))


def _launchd_parent(path: str | Path) -> str:
    """Return one POSIX parent directory without consulting the host path flavor."""
    value = path.as_posix() if isinstance(path, Path) else path
    return posixpath.dirname(value)


def _launchd_path() -> str:
    """Build the explicit tool search path inherited by launchd workers."""
    candidates = (
        _launchd_parent(sys.executable),
        _launchd_parent(launcher_path()),
        *_LAUNCHD_HOMEBREW_DIRS,
        *_launchd_session_path_entries(),
        *_LAUNCHD_SYSTEM_DIRS,
    )
    entries = tuple(
        dict.fromkeys(entry for entry in candidates if posixpath.isabs(entry))
    )
    return _LAUNCHD_PATH_SEPARATOR.join(entries)


def _launcher_text(
    runtime_digest: str | None = None,
    profile_id: str | None = None,
) -> str:
    selected = (
        active_worker_runtime_digest()
        if runtime_digest is None
        else runtime_digest
    )
    if profile_id is not None:
        worker_profile_dir(profile_id)
        if selected is None:
            raise ValueError(
                "profile-bound worker service requires a runtime digest"
            )
        profile_setup = (
            f"os.environ[{WORKER_PROFILE_ID_ENV!r}] = {profile_id!r}"
        )
        run_args = json.dumps(["run", profile_id])
    else:
        profile_setup = ""
        run_args = json.dumps(["run"])
    if selected is not None:
        worker_runtime_dir_for_digest(selected)
        runtime_setup = f"""\
runtime_digest = {selected!r}
runtime_dir = state_dir / "runtimes" / runtime_digest
if not runtime_dir.is_dir():
    raise SystemExit("managed worker runtime is unavailable")
sys.path.insert(0, str(runtime_dir))
os.environ[{WORKER_RUNTIME_DIGEST_ENV!r}] = runtime_digest
"""
    else:
        runtime_setup = """\
runtime_dir = state_dir / "runtime"
if runtime_dir.is_dir():
    sys.path.insert(0, str(runtime_dir))
"""
    return f"""\

import os
import sys
from pathlib import Path

state_dir = Path(__file__).resolve().parents[1]
{runtime_setup.rstrip()}
os.environ.setdefault("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(state_dir))
{profile_setup}
os.environ["LOCAL_SHELL_MCP_REMOTE_WORKER_RUNTIME"] = "1"
os.environ["LOCAL_SHELL_MCP_WORKER_MANAGED"] = "1"
from local_shell_mcp.remote_worker.compat import main
main({run_args})
"""


def ensure_launcher(
    runtime_digest: str | None = None,
    profile_id: str | None = None,
) -> tuple[Path, bool]:
    """Install the stable private launcher and report whether content changed."""
    path = launcher_path()
    content = _launcher_text(runtime_digest, profile_id)
    changed = path.is_symlink() or not path.is_file()
    if not changed:
        try:
            changed = path.read_text(encoding="utf-8") != content
        except OSError:
            changed = True
    if changed:
        atomic_write_private_text(path, content)
    elif os.name != "nt":
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    return path, changed


def _systemd_quote(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ValueError("systemd unit value contains control characters")
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
    )
    return f'"{escaped}"'


def systemd_unit_text(workdir: str) -> str:
    """Generate one deterministic credential-free user unit."""
    launcher = launcher_path()
    state_dir = runtime.worker_state_dir()
    return "\n".join(
        [
            "[Unit]",
            "Description=local-shell-mcp remote worker",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={_systemd_quote(sys.executable)} {_systemd_quote(str(launcher))}",
            f"WorkingDirectory={_systemd_quote(workdir)}",
            f"Environment={_systemd_quote(f'LOCAL_SHELL_MCP_WORKER_STATE_DIR={state_dir}')}",
            f"Environment={_systemd_quote(f'{_WORKER_MANAGED_ENV}=1')}",
            "Restart=always",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def launchd_plist_bytes(workdir: str) -> bytes:
    """Generate one credential-free plist with an explicit sanitized tool PATH."""
    launcher = launcher_path()
    log_path = launchd_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.suppress(OSError):
        log_path.parent.chmod(0o700)
    payload = {
        "Label": _LAUNCHD_LABEL,
        "ProgramArguments": [sys.executable, str(launcher)],
        "WorkingDirectory": workdir,
        "EnvironmentVariables": {
            "LOCAL_SHELL_MCP_WORKER_STATE_DIR": str(runtime.worker_state_dir()),
            _WORKER_MANAGED_ENV: "1",
            "PATH": _launchd_path(),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "Umask": 0o077,
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def _write_launchd_plist(workdir: str) -> tuple[Path, bool]:
    path = launchd_plist_path()
    content = launchd_plist_bytes(workdir)
    changed = path.is_symlink() or not path.is_file()
    if not changed:
        try:
            changed = path.read_bytes() != content
        except OSError:
            changed = True
    if changed:
        atomic_write_private_bytes(path, content)
    return path, changed


def _installed_launchd_workdir() -> str | None:
    path = launchd_plist_path()
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = plistlib.loads(path.read_bytes())
    except OSError, TypeError, ValueError, plistlib.InvalidFileException:
        return None
    workdir = payload.get("WorkingDirectory")
    return workdir if isinstance(workdir, str) and workdir else None


def refresh_installed_service_definition(
    identity: dict[str, Any],
    runtime_digest: str | None = None,
) -> bool:
    """Refresh an installed managed launcher without changing service state."""
    manager = service_manager()
    path = systemd_unit_path() if manager == "systemd" else launchd_plist_path()
    if manager == "unsupported" or not path.is_file():
        return False
    workdir = _identity_workdir(identity)
    profile_id = _identity_profile_id(identity)
    selected_digest = (
        _identity_runtime_digest(identity)
        if runtime_digest is None
        else runtime_digest
    )
    _launcher, launcher_changed = ensure_launcher(selected_digest, profile_id)
    if manager == "systemd":
        return launcher_changed
    _path, definition_changed = _write_launchd_plist(workdir)
    return launcher_changed or definition_changed


def prepare_worker_service_environment(
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """Repair PATH for one managed launchd worker and refresh its next launch."""
    path = launchd_plist_path()
    if (
        platform.system() != "Darwin"
        or os.getenv(_WORKER_MANAGED_ENV) != "1"
        or not path.is_file()
    ):
        return None
    workdir = _installed_launchd_workdir()
    if workdir is None:
        return None
    active_environ = os.environ if environ is None else environ
    active_environ["PATH"] = _launchd_path()
    refreshed, _changed = _write_launchd_plist(workdir)
    return refreshed


def _parse_systemd_show(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            parsed[name] = value
    return parsed


def _unsupported_status() -> WorkerServiceStatus:
    return WorkerServiceStatus(
        schema_version=1,
        manager="unsupported",
        supported=False,
        available=False,
        installed=False,
        enabled=False,
        running=False,
        pid=None,
        state="unsupported",
        unit_path=None,
        log_path=None,
    )


def _systemd_status() -> WorkerServiceStatus:
    path = systemd_unit_path()
    executable = _manager_executable("systemd")
    if executable is None:
        return WorkerServiceStatus(
            1,
            "systemd",
            True,
            False,
            path.is_file(),
            False,
            False,
            None,
            "unavailable",
            str(path),
            None,
        )
    if not path.is_file():
        return WorkerServiceStatus(
            1,
            "systemd",
            True,
            True,
            False,
            False,
            False,
            None,
            "not_installed",
            str(path),
            None,
        )
    result = _run(
        [
            executable,
            "--user",
            "show",
            f"{_SERVICE_NAME}.service",
            "--property=LoadState,UnitFileState,ActiveState,SubState,MainPID",
        ]
    )
    if result.returncode != 0:
        return WorkerServiceStatus(
            1,
            "systemd",
            True,
            False,
            True,
            False,
            False,
            None,
            "unavailable",
            str(path),
            None,
        )
    values = _parse_systemd_show(result.stdout)
    active_state = values.get("ActiveState", "")
    sub_state = values.get("SubState", "")
    running = active_state == "active" and sub_state in {"running", "exited"}
    pid_text = values.get("MainPID", "")
    pid = int(pid_text) if pid_text.isdigit() and int(pid_text) > 0 else None
    unit_state = values.get("UnitFileState", "")
    enabled = unit_state in {"enabled", "enabled-runtime", "static"}
    state: ServiceState
    if running:
        state = "running"
    elif active_state == "failed":
        state = "failed"
    elif active_state in {"inactive", "deactivating", "activating"}:
        state = "stopped"
    else:
        state = "unknown"
    return WorkerServiceStatus(
        1,
        "systemd",
        True,
        True,
        True,
        enabled,
        running,
        pid,
        state,
        str(path),
        None,
    )


def _launchd_status() -> WorkerServiceStatus:
    path = launchd_plist_path()
    log_path = launchd_log_path()
    executable = _manager_executable("launchd")
    if executable is None:
        return WorkerServiceStatus(
            1,
            "launchd",
            True,
            False,
            path.is_file(),
            path.is_file(),
            False,
            None,
            "unavailable",
            str(path),
            str(log_path),
        )
    if not path.is_file():
        return WorkerServiceStatus(
            1,
            "launchd",
            True,
            True,
            False,
            False,
            False,
            None,
            "not_installed",
            str(path),
            str(log_path),
        )
    result = _run([executable, "print", _launchd_target()])
    if result.returncode != 0:
        return WorkerServiceStatus(
            1,
            "launchd",
            True,
            True,
            True,
            True,
            False,
            None,
            "stopped",
            str(path),
            str(log_path),
        )
    pid_match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", result.stdout)
    state_match = re.search(r"(?m)^\s*state\s*=\s*(\S+)\s*$", result.stdout)
    pid = int(pid_match.group(1)) if pid_match else None
    running = pid is not None or (
        state_match is not None and state_match.group(1).lower() == "running"
    )
    return WorkerServiceStatus(
        1,
        "launchd",
        True,
        True,
        True,
        True,
        running,
        pid,
        "running" if running else "stopped",
        str(path),
        str(log_path),
    )


def service_status() -> WorkerServiceStatus:
    """Return truthful native user-service state without raising for absence."""
    manager = service_manager()
    if manager == "systemd":
        return _systemd_status()
    if manager == "launchd":
        return _launchd_status()
    return _unsupported_status()


def _require_supported_available() -> tuple[ServiceManager, str]:
    manager = service_manager()
    if manager == "unsupported":
        raise WorkerServiceError(
            "worker user-service management is unsupported on this platform"
        )
    executable = _manager_executable(manager)
    if executable is None:
        raise WorkerServiceError(
            f"{manager} user-service manager is unavailable"
        )
    return manager, executable


def _identity_profile_id(identity: dict[str, Any]) -> str | None:
    raw_profile_id = identity.get("profile_id")
    if raw_profile_id in {None, ""}:
        return None
    if not isinstance(raw_profile_id, str):
        raise WorkerServiceError(
            "stored worker identity has an invalid profile id"
        )
    try:
        worker_profile_dir(raw_profile_id)
    except ValueError as exc:
        raise WorkerServiceError(
            "stored worker identity has an invalid profile id"
        ) from exc
    return raw_profile_id


def _identity_runtime_digest(identity: dict[str, Any]) -> str | None:
    profile_id = _identity_profile_id(identity)
    if profile_id is None:
        return active_worker_runtime_digest()
    try:
        profile = read_worker_profile(profile_id)
    except (OSError, ValueError) as exc:
        raise WorkerServiceError(
            "stored worker profile is unavailable"
        ) from exc
    digest = str(profile.get("runtime_sha256") or "")
    try:
        installed = runtime.runtime_identity(digest)
    except ValueError as exc:
        raise WorkerServiceError(
            "stored worker profile runtime is invalid"
        ) from exc
    if installed.get("sha256") != digest:
        raise WorkerServiceError("stored worker profile runtime is unavailable")
    return digest


def _identity_workdir(identity: dict[str, Any]) -> str:
    workdir = str(identity.get("workdir") or "")
    if not workdir:
        raise WorkerServiceError("stored worker identity has no workdir")
    return str(Path(workdir).expanduser().resolve())


def install_service(
    identity: dict[str, Any], *, start: bool = True
) -> WorkerServiceResult:
    """Install and enable the native per-user worker service idempotently."""
    manager, executable = _require_supported_available()
    workdir = _identity_workdir(identity)
    profile_id = _identity_profile_id(identity)
    runtime_digest = _identity_runtime_digest(identity)
    before = service_status()
    _launcher, launcher_changed = ensure_launcher(runtime_digest, profile_id)
    if manager == "systemd":
        path = systemd_unit_path()
        content = systemd_unit_text(workdir)
        changed = launcher_changed or (
            not path.is_file() or path.read_text(encoding="utf-8") != content
        )
        if changed:
            atomic_write_private_text(path, content)
        _run_checked([executable, "--user", "daemon-reload"])
        command = [executable, "--user", "enable"]
        if start:
            command.append("--now")
        command.append(f"{_SERVICE_NAME}.service")
        _run_checked(command)
        if start and changed and before.running:
            _run_checked(
                [executable, "--user", "restart", f"{_SERVICE_NAME}.service"]
            )
    else:
        path, definition_changed = _write_launchd_plist(workdir)
        changed = launcher_changed or definition_changed
        _run_checked([executable, "enable", _launchd_target()])
        if start:
            current = _launchd_status()
            if current.running and changed:
                _run_checked(
                    [executable, "bootout", _launchd_target()],
                    allowed_returncodes={0, 3, 113},
                )
                _run_checked(
                    [executable, "bootstrap", _launchd_domain(), str(path)]
                )
            elif not current.running:
                _run_checked(
                    [executable, "bootstrap", _launchd_domain(), str(path)]
                )
    after = service_status()
    lifecycle_changed = changed or before.enabled != after.enabled
    if start:
        lifecycle_changed = lifecycle_changed or before.running != after.running
    return WorkerServiceResult(1, "install-service", lifecycle_changed, after)


def uninstall_service() -> WorkerServiceResult:
    """Disable and remove the native user service idempotently."""
    manager, executable = _require_supported_available()
    before = service_status()
    changed = before.installed or before.running or before.enabled
    if manager == "systemd":
        _run_checked(
            [
                executable,
                "--user",
                "disable",
                "--now",
                f"{_SERVICE_NAME}.service",
            ],
            allowed_returncodes={0, 1, 5},
        )
        systemd_unit_path().unlink(missing_ok=True)
        _run_checked([executable, "--user", "daemon-reload"])
        _run_checked(
            [executable, "--user", "reset-failed", f"{_SERVICE_NAME}.service"],
            allowed_returncodes={0, 1, 5},
        )
    else:
        _run_checked(
            [executable, "bootout", _launchd_target()],
            allowed_returncodes={0, 3, 113},
        )
        _run_checked(
            [executable, "disable", _launchd_target()],
            allowed_returncodes={0, 3},
        )
        launchd_plist_path().unlink(missing_ok=True)
    return WorkerServiceResult(
        1, "uninstall-service", changed, service_status()
    )


def _mutate_service(
    action: Literal["start", "stop", "restart"],
) -> WorkerServiceResult:
    manager, executable = _require_supported_available()
    before = service_status()
    if not before.installed:
        raise WorkerServiceError("worker user service is not installed")
    if manager == "systemd":
        _run_checked([executable, "--user", action, f"{_SERVICE_NAME}.service"])
    elif action == "stop":
        _run_checked(
            [executable, "bootout", _launchd_target()],
            allowed_returncodes={0, 3, 113},
        )
    elif action == "start" and before.running:
        pass
    elif before.running:
        _run_checked([executable, "kickstart", "-k", _launchd_target()])
    else:
        _run_checked(
            [
                executable,
                "bootstrap",
                _launchd_domain(),
                str(launchd_plist_path()),
            ]
        )
    after = service_status()
    desired_changed = (
        before.running != after.running
        if action != "restart"
        else before.running or after.running
    )
    return WorkerServiceResult(1, action, desired_changed, after)


def start_service() -> WorkerServiceResult:
    """Start the installed user service."""
    return _mutate_service("start")


def stop_service() -> WorkerServiceResult:
    """Stop the installed user service."""
    return _mutate_service("stop")


def restart_service() -> WorkerServiceResult:
    """Restart or start the installed user service."""
    return _mutate_service("restart")


def _bounded_tail(path: Path, lines: int) -> str:
    if path.is_symlink() or not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - _MAX_LOG_BYTES))
        data = handle.read(_MAX_LOG_BYTES)
    decoded = data.decode("utf-8", errors="replace")
    return "\n".join(decoded.splitlines()[-lines:])


def _log_tail_signature(path: Path, size: int) -> bytes | None:
    """Fingerprint the bounded retained tail to detect coarse-timestamp rewrites."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, size - _MAX_LOG_BYTES))
            digest = hashlib.blake2b(digest_size=16)
            remaining = _MAX_LOG_BYTES
            while remaining > 0:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
        return digest.digest()
    except OSError:
        return None


def _follow_private_log(path: Path, lines: int) -> None:
    initial = _bounded_tail(path, lines)
    if initial:
        print(initial, flush=True)
    try:
        initial = (
            path.stat() if path.exists() and not path.is_symlink() else None
        )
    except OSError:
        initial = None
    position = initial.st_size if initial is not None else 0
    identity = (initial.st_dev, initial.st_ino) if initial is not None else None
    modified_ns = initial.st_mtime_ns if initial is not None else None
    signature = (
        _log_tail_signature(path, initial.st_size)
        if initial is not None
        else None
    )
    try:
        while True:
            if path.exists() and not path.is_symlink():
                info = path.stat()
                current_identity = (info.st_dev, info.st_ino)
                replaced = identity is not None and current_identity != identity
                rewritten = (
                    modified_ns is not None
                    and info.st_mtime_ns != modified_ns
                    and info.st_size <= position
                )
                current_signature = None
                if not replaced and info.st_size <= position:
                    current_signature = _log_tail_signature(path, info.st_size)
                    rewritten = rewritten or (
                        signature is not None
                        and current_signature is not None
                        and current_signature != signature
                    )
                if replaced or rewritten or info.st_size < position:
                    position = 0
                identity = current_identity
                modified_ns = info.st_mtime_ns
                if info.st_size > position:
                    with path.open(
                        "r", encoding="utf-8", errors="replace"
                    ) as handle:
                        handle.seek(position)
                        chunk = handle.read(_MAX_LOG_BYTES)
                        position = handle.tell()
                    if chunk:
                        print(chunk, end="", flush=True)
                signature = _log_tail_signature(path, info.st_size)
            time.sleep(0.25)
    except KeyboardInterrupt:
        return


def service_logs(*, lines: int = 100, follow: bool = False) -> None:
    """Print bounded native worker logs, optionally following until interrupted."""
    bounded_lines = max(1, min(int(lines), _MAX_LOG_LINES))
    manager, executable = _require_supported_available()
    status = service_status()
    if not status.installed:
        raise WorkerServiceError("worker user service is not installed")
    if manager == "systemd":
        command = [
            shutil.which("journalctl") or "journalctl",
            "--user",
            "--unit",
            f"{_SERVICE_NAME}.service",
            "--lines",
            str(bounded_lines),
            "--no-pager",
        ]
        if follow:
            command.append("--follow")
            try:
                subprocess.run(command, check=False)  # noqa: S603
            except KeyboardInterrupt:
                return
        else:
            result = _run_checked(command, timeout=30)
            output = result.stdout.encode("utf-8")[-_MAX_LOG_BYTES:].decode(
                "utf-8", errors="replace"
            )
            print(output, end="" if output.endswith("\n") else "\n")
        return
    path = launchd_log_path()
    if follow:
        _follow_private_log(path, bounded_lines)
    else:
        output = _bounded_tail(path, bounded_lines)
        if output:
            print(output)


def status_json(status: WorkerServiceStatus | WorkerServiceResult) -> str:
    """Serialize one typed service result deterministically."""
    return json.dumps(status.to_dict(), sort_keys=True)
