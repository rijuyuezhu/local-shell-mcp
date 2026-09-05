import argparse
import io
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import workgate.remote_worker.cli as worker_cli
import workgate.remote_worker.runtime as runtime
import workgate.remote_worker.service as service
import workgate.remote_worker.worker as worker
from workgate.main import _build_parser
from workgate.remote_worker.profiles import (
    read_worker_profile,
    update_worker_profile,
)


@pytest.fixture(autouse=True)
def _worker_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv(
        "WORKGATE_WORKER_STATE_DIR", str(tmp_path / "worker-state")
    )
    monkeypatch.delenv("WORKGATE_REMOTE_WORKER_RUNTIME", raising=False)
    monkeypatch.delenv("WORKGATE_WORKER_MANAGED", raising=False)
    yield


def _identity(tmp_path: Path) -> dict[str, str]:
    workdir = tmp_path / "work dir"
    workdir.mkdir(exist_ok=True)
    return {
        "server": "https://controller.test",
        "name": "worker-a",
        "access": "private-worker-access",
        "workdir": str(workdir),
    }


def _profile_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile_id: str = "p_abcdefgh",
    digest: str = "a" * 64,
) -> dict[str, str]:
    identity = {**_identity(tmp_path), "profile_id": profile_id}
    worker._write_worker_identity(identity, profile_id)
    update_worker_profile(
        profile_id,
        runtime_sha256=digest,
        runtime_version="4.0.0",
        server=identity["server"],
        name=identity["name"],
        workdir=identity["workdir"],
    )
    monkeypatch.setattr(
        service.runtime,
        "runtime_identity",
        lambda selected: {"sha256": selected, "version": "4.0.0"},
    )
    return identity


class _SystemdFake:
    def __init__(self) -> None:
        self.enabled = False
        self.running = False
        self.failed = False
        self.commands: list[list[str]] = []

    def run(
        self, command: list[str], *, timeout: float = 15
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        action = (
            command[2]
            if command[:2] == ["/usr/bin/systemctl", "--user"]
            else ""
        )
        if action == "show":
            active = (
                "failed"
                if self.failed
                else ("active" if self.running else "inactive")
            )
            sub = (
                "failed"
                if self.failed
                else ("running" if self.running else "dead")
            )
            output = "\n".join(
                [
                    "LoadState=loaded",
                    f"UnitFileState={'enabled' if self.enabled else 'disabled'}",
                    f"ActiveState={active}",
                    f"SubState={sub}",
                    f"MainPID={321 if self.running else 0}",
                ]
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if action == "enable":
            self.enabled = True
            self.running = "--now" in command
        elif action == "disable":
            self.enabled = False
            self.running = False
        elif action == "start":
            self.running = True
        elif action == "stop":
            self.running = False
        elif action == "restart":
            self.running = True
        return subprocess.CompletedProcess(command, 0, "", "")


def _configure_systemd(monkeypatch: pytest.MonkeyPatch) -> _SystemdFake:
    fake = _SystemdFake()
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: (
            f"/usr/bin/{name}" if name in {"systemctl", "journalctl"} else None
        ),
    )
    monkeypatch.setattr(service, "_run", fake.run)
    return fake


def test_systemd_install_is_private_idempotent_and_credential_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    identity = _identity(tmp_path)

    first = service.install_service(identity)
    second = service.install_service(identity)

    assert first.changed is True
    assert first.status.running is True
    assert second.changed is False
    assert fake.enabled is True
    unit = service.systemd_unit_path()
    launcher = service.launcher_path()
    text = unit.read_text(encoding="utf-8")
    launcher_text = launcher.read_text(encoding="utf-8")
    for secret in (identity["access"], identity["server"], "--invite"):
        assert secret not in text
        assert secret not in launcher_text
    assert "worker-launcher.py" in text
    assert 'run_worker_cli(["run"])' in launcher_text
    assert service._systemd_quote(identity["workdir"]) in text
    if os.name != "nt":
        assert unit.stat().st_mode & 0o777 == 0o600
        assert launcher.stat().st_mode & 0o777 == 0o600

    first_uninstall = service.uninstall_service()
    second_uninstall = service.uninstall_service()
    assert first_uninstall.changed is True
    assert second_uninstall.changed is False
    assert not unit.exists()


def test_systemd_service_binds_one_profile_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    digest = "b" * 64
    identity = _profile_identity(
        tmp_path, monkeypatch, profile_id="p_abcdefgh", digest=digest
    )

    first = service.install_service(identity, start=False)
    second = service.install_service(identity, start=False)

    assert first.changed is True
    assert second.changed is False
    assert fake.enabled is True
    launcher = service.launcher_path().read_text(encoding="utf-8")
    assert f"runtime_digest = {digest!r}" in launcher
    assert (
        "os.environ['WORKGATE_WORKER_PROFILE_ID'] = 'p_abcdefgh'"
    ) in launcher
    assert '"-m", "workgate.remote_worker", *["run", "p_abcdefgh"]' in launcher
    assert identity["access"] not in launcher
    assert identity["server"] not in launcher


def test_systemd_no_start_status_and_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    installed = service.install_service(_identity(tmp_path), start=False)
    assert installed.status.enabled is True
    assert installed.status.running is False

    started = service.start_service()
    restarted = service.restart_service()
    stopped = service.stop_service()

    assert started.status.running is True
    assert restarted.status.running is True
    assert stopped.status.running is False
    assert [
        command[2]
        for command in fake.commands
        if command[:2] == ["/usr/bin/systemctl", "--user"]
    ].count("restart") == 1


def test_systemd_status_reports_unavailable_failed_and_parses_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    service.systemd_unit_path().parent.mkdir(parents=True)
    service.systemd_unit_path().touch()
    fake.enabled = True
    fake.running = True
    status = service.service_status()
    assert status.to_dict() == {
        "schema_version": 1,
        "manager": "systemd",
        "supported": True,
        "available": True,
        "installed": True,
        "enabled": True,
        "running": True,
        "pid": 321,
        "state": "running",
        "unit_path": str(service.systemd_unit_path()),
        "log_path": None,
    }

    fake.running = False
    fake.failed = True
    assert service.service_status().state == "failed"

    monkeypatch.setattr(service.shutil, "which", lambda _name: None)
    unavailable = service.service_status()
    assert unavailable.available is False
    assert unavailable.state == "unavailable"


def test_systemd_command_failure_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_systemd(monkeypatch)
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, timeout=15: subprocess.CompletedProcess(
            command, 9, "sensitive stdout", "sensitive stderr"
        ),
    )
    with pytest.raises(
        service.WorkerServiceError, match="exited with 9"
    ) as error:
        service.install_service(_identity(tmp_path))
    assert "sensitive" not in str(error.value)


class _LaunchdFake:
    def __init__(self) -> None:
        self.loaded = False
        self.commands: list[list[str]] = []

    def run(
        self, command: list[str], *, timeout: float = 15
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        action = command[1] if len(command) > 1 else ""
        if action == "print":
            if not self.loaded:
                return subprocess.CompletedProcess(
                    command, 113, "", "not loaded"
                )
            return subprocess.CompletedProcess(
                command, 0, "service = {\n state = running\n pid = 456\n}\n", ""
            )
        if action == "bootstrap":
            self.loaded = True
        elif action == "bootout":
            self.loaded = False
        elif action == "kickstart":
            self.loaded = True
        return subprocess.CompletedProcess(command, 0, "", "")


def _configure_launchd(monkeypatch: pytest.MonkeyPatch) -> _LaunchdFake:
    fake = _LaunchdFake()
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: "/bin/launchctl" if name == "launchctl" else None,
    )
    monkeypatch.setattr(service, "_run", fake.run)
    return fake


def test_launchd_plist_lifecycle_and_private_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake = _configure_launchd(monkeypatch)
    identity = _identity(tmp_path)

    installed = service.install_service(identity, start=False)
    assert installed.status.running is False
    plist = plistlib.loads(service.launchd_plist_path().read_bytes())
    assert plist["ProgramArguments"] == [
        sys.executable,
        str(service.launcher_path()),
    ]
    assert plist["WorkingDirectory"] == identity["workdir"]
    environment = plist["EnvironmentVariables"]
    assert environment["WORKGATE_WORKER_MANAGED"] == "1"
    path_entries = environment["PATH"].split(":")
    for required in (
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ):
        assert required in path_entries
    serialized = json.dumps(plist)
    assert identity["access"] not in serialized
    assert identity["server"] not in serialized
    assert "invite" not in serialized.lower()

    started = service.start_service()
    assert started.status.running is True
    assert started.status.pid == 456
    service.restart_service()
    assert any(command[1] == "kickstart" for command in fake.commands)

    log = service.launchd_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    service.service_logs(lines=2)
    assert capsys.readouterr().out == "two\nthree\n"

    stopped = service.stop_service()
    assert stopped.status.running is False
    assert service.uninstall_service().status.installed is False


def test_launchd_path_uses_sanitized_session_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.sys, "executable", "/custom/python/bin/python")
    monkeypatch.setattr(
        service,
        "launcher_path",
        lambda: Path("/private/worker/bin/launcher.py"),
    )
    monkeypatch.setattr(service.shutil, "which", lambda name: "/bin/launchctl")
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, timeout=15: subprocess.CompletedProcess(
            command,
            0,
            "/nix/bin:relative::/opt/local/bin:/usr/bin:/nix/bin\n",
            "",
        ),
    )

    entries = service._launchd_path().split(":")

    assert entries[:2] == ["/custom/python/bin", "/private/worker/bin"]
    assert "/opt/homebrew/bin" in entries
    assert "/nix/bin" in entries
    assert "/opt/local/bin" in entries
    assert "relative" not in entries
    assert entries.count("/nix/bin") == 1
    assert entries.count("/usr/bin") == 1


def test_launchd_plist_does_not_inherit_installer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_launchd(monkeypatch)
    identity = _identity(tmp_path)
    first = service.launchd_plist_bytes(identity["workdir"])
    monkeypatch.setenv("PATH", "/tmp/transient-bin:/usr/bin")
    second = service.launchd_plist_bytes(identity["workdir"])

    assert second == first
    assert (
        "/tmp/transient-bin"
        not in plistlib.loads(second)["EnvironmentVariables"]["PATH"]
    )


def test_prepare_launchd_environment_repairs_running_worker_and_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_launchd(monkeypatch)
    identity = _identity(tmp_path)
    service.install_service(identity, start=False)
    path = service.launchd_plist_path()
    payload = plistlib.loads(path.read_bytes())
    payload["EnvironmentVariables"].pop("PATH")
    path.write_bytes(plistlib.dumps(payload))
    monkeypatch.setenv("WORKGATE_WORKER_MANAGED", "1")
    monkeypatch.setattr(
        service, "_launchd_session_path_entries", lambda: ("/opt/local/bin",)
    )

    environment = {"PATH": "/transient"}
    assert service.prepare_worker_service_environment(environment) == path
    entries = environment["PATH"].split(":")
    assert "/opt/homebrew/bin" in entries
    assert "/opt/local/bin" in entries
    refreshed = plistlib.loads(path.read_bytes())
    assert refreshed["EnvironmentVariables"]["PATH"] == environment["PATH"]


def test_prepare_launchd_environment_preserves_profile_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_launchd(monkeypatch)
    identity = _profile_identity(tmp_path, monkeypatch)
    service.install_service(identity, start=False)
    launcher = service.launcher_path()
    original = launcher.read_text(encoding="utf-8")
    monkeypatch.setenv("WORKGATE_WORKER_MANAGED", "1")

    assert service.prepare_worker_service_environment({}) == (
        service.launchd_plist_path()
    )
    assert launcher.read_text(encoding="utf-8") == original
    assert '"-m", "workgate.remote_worker", *["run", "p_abcdefgh"]' in original


def test_prepare_launchd_environment_rejects_symlinked_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_launchd(monkeypatch)
    identity = _identity(tmp_path)
    path = service.launchd_plist_path()
    path.parent.mkdir(parents=True)
    target = tmp_path / "foreign.plist"
    target.write_bytes(service.launchd_plist_bytes(identity["workdir"]))
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink unavailable")
    monkeypatch.setenv("WORKGATE_WORKER_MANAGED", "1")
    environment = {"PATH": "/unchanged"}

    assert service.prepare_worker_service_environment(environment) is None
    assert path.is_symlink()
    assert environment == {"PATH": "/unchanged"}


def test_refresh_stopped_launchd_definition_without_lifecycle_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_launchd(monkeypatch)
    identity = _identity(tmp_path)
    service.install_service(identity, start=False)
    path = service.launchd_plist_path()
    path.write_bytes(b"stale")
    fake.commands.clear()

    assert service.refresh_installed_service_definition(identity) is True
    assert plistlib.loads(path.read_bytes())["EnvironmentVariables"]["PATH"]
    assert fake.commands == [["/bin/launchctl", "getenv", "PATH"]]


def test_service_status_and_install_are_explicitly_unsupported_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Windows")
    status = service.service_status()
    assert status.manager == "unsupported"
    assert status.supported is False
    with pytest.raises(service.WorkerServiceError, match="unsupported"):
        service.install_service({})


def test_bounded_launchd_log_tail_and_follow_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _configure_launchd(monkeypatch)
    path = service.launchd_plist_path()
    path.parent.mkdir(parents=True)
    path.touch()
    log = service.launchd_log_path()
    log.parent.mkdir(parents=True)
    log.write_text(
        "\n".join(f"line-{index}" for index in range(3_000)), encoding="utf-8"
    )
    service.service_logs(lines=20_000)
    output = capsys.readouterr().out
    assert "line-1000" in output
    assert "line-999" not in output

    monkeypatch.setattr(
        service.time,
        "sleep",
        lambda _delay: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    service.service_logs(lines=1, follow=True)
    assert "line-2999" in capsys.readouterr().out


def test_worker_cli_contract_and_invite_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "worker",
            "enroll",
            "--server",
            "https://controller.test",
            "--invite-stdin",
        ]
    )
    assert args.worker_command == "enroll"
    assert not hasattr(args, "persist")

    stdin = SimpleNamespace(
        isatty=lambda: False,
        buffer=io.BytesIO(b"invite-from-stdin\r\n"),
    )
    monkeypatch.setattr(worker_cli.sys, "stdin", stdin)
    assert worker_cli._read_invite(args) == "invite-from-stdin"

    monkeypatch.setattr(
        worker_cli.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True, buffer=io.BytesIO()),
    )
    with pytest.raises(ValueError, match="TTY"):
        worker_cli._read_invite(args)


def test_invite_stdin_is_bounded_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(invite=None, invite_stdin=True)
    monkeypatch.setattr(
        worker_cli.sys,
        "stdin",
        SimpleNamespace(
            isatty=lambda: False,
            buffer=io.BytesIO(b"x" * (worker_cli._MAX_INVITE_BYTES + 1)),
        ),
    )
    with pytest.raises(ValueError, match="size limit"):
        worker_cli._read_invite(args)

    monkeypatch.setattr(
        worker_cli.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(b"\xff")),
    )
    with pytest.raises(ValueError, match="UTF-8"):
        worker_cli._read_invite(args)


@pytest.mark.asyncio
async def test_enroll_stores_identity_without_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        worker, "_configure_worker_runtime_env", lambda _path: None
    )
    monkeypatch.setattr(worker, "_read_worker_identity", lambda *_args: None)
    stored: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "_write_worker_identity", stored.append)

    async def post(url, payload, *_args, **_kwargs):
        assert url.endswith("/register")
        assert payload["invite"] == "one-time-invite"
        return {
            "ok": True,
            "data": {"token": "private-access", "name": "worker-a"},
        }

    monkeypatch.setattr(worker, "_worker_post_json_forever", post)
    identity = await worker.enroll_worker(
        "https://controller.test/",
        "one-time-invite",
        "worker-a",
        str(tmp_path),
    )
    assert identity["server"] == "https://controller.test"
    assert identity["access"] == "private-access"
    assert stored == [identity]


@pytest.mark.asyncio
async def test_run_stored_worker_uses_only_persisted_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker,
        "load_worker_identity",
        lambda: {
            "server": "https://controller.test",
            "name": "worker-a",
            "access": "secret",
            "workdir": "/work",
        },
    )
    calls: list[tuple[Any, ...]] = []

    async def run(*args):
        calls.append(args)

    monkeypatch.setattr(worker, "run_worker", run)
    await worker.run_stored_worker()
    assert calls == [("https://controller.test", "", "worker-a", "/work")]


def test_cli_enroll_output_never_contains_invite_or_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    async def enroll(*_args):
        return {
            "server": "https://controller.test",
            "name": "worker-a",
            "access": "private-access",
            "workdir": str(tmp_path),
        }

    monkeypatch.setattr(worker, "enroll_worker", enroll)
    args = _build_parser().parse_args(
        [
            "worker",
            "enroll",
            "--server",
            "https://controller.test",
            "--invite",
            "one-time-invite",
        ]
    )
    args.handler(args)
    output = capsys.readouterr().out
    assert "one-time-invite" not in output
    assert "private-access" not in output
    assert json.loads(output)["enrolled"] is True


def test_update_restarts_only_previously_running_service(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        worker_cli,
        "_load_identity",
        lambda: {"server": "https://controller.test"},
    )
    monkeypatch.setattr(
        runtime,
        "update_installed_runtime",
        lambda server, force=False: {
            "updated": True,
            "version": "4.0.0",
            "sha256": "a" * 64,
        },
    )
    running = service.WorkerServiceStatus(
        1,
        "systemd",
        True,
        True,
        True,
        True,
        True,
        123,
        "running",
        "/unit",
        None,
    )
    monkeypatch.setattr(service, "service_status", lambda: running)
    restarts: list[bool] = []
    refreshes: list[tuple[dict[str, str], str | None]] = []
    monkeypatch.setattr(
        service, "restart_service", lambda: restarts.append(True)
    )
    monkeypatch.setattr(
        service,
        "refresh_installed_service_definition",
        lambda identity, runtime_digest=None: (
            refreshes.append((identity, runtime_digest)) or False
        ),
    )

    worker_cli._update_from_args(argparse.Namespace(force=True))
    result = json.loads(capsys.readouterr().out)
    assert result["service_restarted"] is True
    assert restarts == [True]
    assert refreshes == [({"server": "https://controller.test"}, "a" * 64)]

    stopped = service.WorkerServiceStatus(
        1,
        "systemd",
        True,
        True,
        True,
        True,
        False,
        None,
        "stopped",
        "/unit",
        None,
    )
    monkeypatch.setattr(service, "service_status", lambda: stopped)
    restarts.clear()
    worker_cli._update_from_args(argparse.Namespace(force=False))
    assert json.loads(capsys.readouterr().out)["service_restarted"] is False
    assert restarts == []
    assert refreshes == [
        ({"server": "https://controller.test"}, "a" * 64),
        ({"server": "https://controller.test"}, "a" * 64),
    ]


def test_cli_install_and_update_bind_explicit_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    profile_id = "p_abcdefgh"
    identity = _profile_identity(tmp_path, monkeypatch, profile_id=profile_id)
    installs: list[tuple[dict[str, str], bool]] = []
    monkeypatch.setattr(service, "service_manager", lambda: "systemd")
    monkeypatch.setattr(
        service,
        "install_service",
        lambda selected, start=True: (
            installs.append((selected, start))
            or _service_result("install-service")
        ),
    )

    install_args = _build_parser().parse_args(
        ["worker", "install-service", profile_id, "--no-start"]
    )
    install_args.handler(install_args)

    assert installs == [(identity, False)]
    assert json.loads(capsys.readouterr().out)["action"] == "install-service"

    new_digest = "c" * 64
    monkeypatch.setattr(service, "service_status", _stopped_status)
    updates: list[tuple[str, bool, str | None]] = []

    def update_runtime(
        server: str,
        *,
        force: bool = False,
        current_version: str | None = None,
    ) -> dict[str, Any]:
        updates.append((server, force, current_version))
        return {
            "updated": True,
            "version": "4.1.0",
            "sha256": new_digest,
        }

    monkeypatch.setattr(runtime, "update_installed_runtime", update_runtime)
    refreshes: list[tuple[dict[str, str], str | None]] = []
    monkeypatch.setattr(
        service,
        "refresh_installed_service_definition",
        lambda selected, runtime_digest=None: (
            refreshes.append((selected, runtime_digest)) or False
        ),
    )

    update_args = _build_parser().parse_args(
        ["worker", "update", profile_id, "--force"]
    )
    update_args.handler(update_args)

    profile = read_worker_profile(profile_id)
    assert profile["runtime_sha256"] == new_digest
    assert profile["runtime_version"] == "4.1.0"
    assert updates == [(identity["server"], True, "4.0.0")]
    assert refreshes == [(identity, new_digest)]
    assert json.loads(capsys.readouterr().out)["service_restarted"] is False


def test_update_fetches_latest_manifest_and_propagates_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = {
        "bundle_version": "4.0.0",
        "sha256": "b" * 64,
    }
    monkeypatch.setattr(
        runtime, "fetch_latest_manifest", lambda _server: manifest
    )
    monkeypatch.setattr(
        runtime,
        "current_runtime_identity",
        lambda: {"sha256": "a" * 64, "bundle_version": "3.9.1"},
    )
    calls: list[tuple[Any, ...]] = []

    def install(server, instruction, *, current_version, force=False):
        calls.append((server, instruction, current_version, force))
        return {
            "updated": True,
            "version": instruction["version"],
            "sha256": instruction["sha256"],
        }

    monkeypatch.setattr(runtime, "install_runtime", install)
    result = runtime.update_installed_runtime(
        "https://controller.test", force=True
    )
    assert result["version"] == "4.0.0"
    assert calls[0][2:] == ("3.9.1", True)

    calls.clear()
    runtime.update_installed_runtime(
        "https://controller.test",
        current_version="3.8.0",
    )
    assert calls[0][2:] == ("3.8.0", False)


def _stopped_status(
    manager: service.ServiceManager = "systemd",
) -> service.WorkerServiceStatus:
    return service.WorkerServiceStatus(
        1,
        manager,
        manager != "unsupported",
        manager != "unsupported",
        manager != "unsupported",
        manager != "unsupported",
        False,
        None,
        "stopped" if manager != "unsupported" else "unsupported",
        "/unit" if manager != "unsupported" else None,
        None,
    )


def _service_result(action: str) -> service.WorkerServiceResult:
    return service.WorkerServiceResult(1, action, True, _stopped_status())


def test_all_worker_service_cli_handlers_emit_typed_json(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        worker, "load_worker_identity", lambda: {"workdir": "/work"}
    )
    monkeypatch.setattr(
        service,
        "install_service",
        lambda identity, start=True: _service_result("install-service"),
    )
    monkeypatch.setattr(
        service,
        "uninstall_service",
        lambda: _service_result("uninstall-service"),
    )
    monkeypatch.setattr(
        service, "start_service", lambda: _service_result("start")
    )
    monkeypatch.setattr(
        service, "stop_service", lambda: _service_result("stop")
    )
    monkeypatch.setattr(
        service, "restart_service", lambda: _service_result("restart")
    )
    monkeypatch.setattr(service, "service_status", _stopped_status)
    log_calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        service,
        "service_logs",
        lambda *, lines, follow: log_calls.append((lines, follow)),
    )

    for command, action in (
        (["install-service", "--no-start"], "install-service"),
        (["uninstall-service"], "uninstall-service"),
        (["start"], "start"),
        (["stop"], "stop"),
        (["restart"], "restart"),
    ):
        args = _build_parser().parse_args(["worker", *command])
        args.handler(args)
        assert json.loads(capsys.readouterr().out)["action"] == action

    status_args = _build_parser().parse_args(["worker", "status"])
    status_args.handler(status_args)
    assert json.loads(capsys.readouterr().out)["state"] == "stopped"

    log_args = _build_parser().parse_args(
        ["worker", "logs", "--lines", "17", "--follow"]
    )
    log_args.handler(log_args)
    assert log_calls == [(17, True)]


def test_service_handler_returns_safe_error_json_and_interrupt(
    capsys,
) -> None:
    def fail(_args):
        raise RuntimeError("private command detail")

    wrapped = worker_cli._service_handler(fail)
    with pytest.raises(SystemExit) as error:
        wrapped(argparse.Namespace())
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "private command detail" not in output
    assert json.loads(output)["error"] == "RuntimeError"

    def interrupt(_args):
        raise KeyboardInterrupt

    with pytest.raises(SystemExit) as interrupted:
        worker_cli._service_handler(interrupt)(argparse.Namespace())
    assert interrupted.value.code == 130


def test_worker_connect_and_run_handlers_mark_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKGATE_REMOTE_WORKER_RUNTIME", raising=False)
    connect_calls: list[tuple[Any, ...]] = []

    async def connect(*args):
        connect_calls.append(args)

    monkeypatch.setattr(worker, "run_worker", connect)
    args = _build_parser().parse_args(
        [
            "worker",
            "connect",
            "--server",
            "https://controller.test",
            "--invite",
            "invite",
        ]
    )
    args.handler(args)
    assert connect_calls == [("https://controller.test", "invite", None, None)]
    assert os.environ["WORKGATE_REMOTE_WORKER_RUNTIME"] == "1"

    run_calls: list[bool] = []

    async def run_stored():
        run_calls.append(True)

    monkeypatch.setattr(worker, "run_stored_worker", run_stored)
    prepared: list[bool] = []
    monkeypatch.setattr(
        service,
        "prepare_worker_service_environment",
        lambda: prepared.append(True),
    )
    run_args = _build_parser().parse_args(["worker", "run"])
    run_args.handler(run_args)
    assert prepared == [True]
    assert run_calls == [True]
    os.environ.pop("WORKGATE_REMOTE_WORKER_RUNTIME", None)


def test_worker_invite_error_and_async_failure_are_clean(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    args = argparse.Namespace(invite=None, invite_stdin=True)
    monkeypatch.setattr(
        worker_cli.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(b"")),
    )
    with pytest.raises(SystemExit) as empty:
        worker_cli._invite_or_exit(args)
    assert empty.value.code == 1
    assert "worker invite is empty" in capsys.readouterr().err

    async def fail():
        raise RuntimeError("redacted-failure")

    with pytest.raises(SystemExit) as failed:
        worker_cli._run_async(fail())
    assert failed.value.code == 1
    assert "redacted-failure" in capsys.readouterr().err


def test_standalone_worker_parser_lists_only_new_commands(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        worker_cli.run_worker_cli(["--help"])
    assert help_exit.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "enroll",
        "connect",
        "run",
        "install-service",
        "uninstall-service",
        "start",
        "stop",
        "restart",
        "status",
        "logs",
        "update",
    ):
        assert command in output
    assert "--persist" not in output


def test_systemd_quote_escapes_specifiers_variables_and_quotes() -> None:
    assert service._systemd_quote('a b%$"\\c') == '"a b%%$$\\"\\\\c"'
    with pytest.raises(ValueError, match="control"):
        service._systemd_quote("bad\nvalue")


def test_service_result_json_and_real_run_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _service_result("start")
    assert (
        json.loads(service.status_json(result))["status"]["state"] == "stopped"
    )
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "ok", ""
        ),
    )
    assert service._run(["command"]).stdout == "ok"
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, timeout=15: (_ for _ in ()).throw(OSError("private")),
    )
    with pytest.raises(service.WorkerServiceError, match="OSError"):
        service._run_checked(["command"])


def test_service_manager_paths_and_unavailable_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    assert str(tmp_path / "profile") in str(service.systemd_unit_path())

    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.shutil, "which", lambda _name: None)
    unavailable = service.service_status()
    assert unavailable.manager == "launchd"
    assert unavailable.state == "unavailable"
    with pytest.raises(service.WorkerServiceError, match="unavailable"):
        service.start_service()
    assert service._manager_executable("unsupported") is None


def test_status_unknown_show_failure_and_missing_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_systemd(monkeypatch)
    assert service.service_status().state == "not_installed"
    service.systemd_unit_path().parent.mkdir(parents=True)
    service.systemd_unit_path().touch()
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, timeout=15: subprocess.CompletedProcess(
            command, 1, "", ""
        ),
    )
    assert service.service_status().state == "unavailable"

    monkeypatch.setattr(
        service,
        "_run",
        lambda command, timeout=15: subprocess.CompletedProcess(
            command,
            0,
            "ActiveState=mystery\nSubState=mystery\nMainPID=nope\nUnitFileState=disabled\n",
            "",
        ),
    )
    unknown = service.service_status()
    assert unknown.state == "unknown"
    assert unknown.pid is None
    with pytest.raises(service.WorkerServiceError, match="not installed"):
        service.systemd_unit_path().unlink()
        service.start_service()


def test_install_requires_workdir_and_reloads_running_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    with pytest.raises(service.WorkerServiceError, match="workdir"):
        service.install_service({})

    identity = _identity(tmp_path)
    service.install_service(identity)
    fake.commands.clear()
    service.systemd_unit_path().write_text("stale", encoding="utf-8")
    fake.running = True
    fake.enabled = True
    service.install_service(identity)
    assert any(command[2] == "restart" for command in fake.commands)

    launchd = _configure_launchd(monkeypatch)
    service.install_service(identity)
    service.launchd_plist_path().write_bytes(b"stale")
    launchd.loaded = True
    launchd.commands.clear()
    service.install_service(identity)
    actions = [command[1] for command in launchd.commands]
    assert "bootout" in actions
    assert "bootstrap" in actions


def test_changed_launcher_restarts_running_systemd_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    identity = _identity(tmp_path)
    service.install_service(identity)
    fake.commands.clear()
    service.launcher_path().write_text("stale launcher", encoding="utf-8")
    fake.running = True
    fake.enabled = True

    result = service.install_service(identity)

    assert result.changed is True
    assert (
        service.launcher_path().read_text(encoding="utf-8")
        == service._launcher_text()
    )
    assert any(command[2] == "restart" for command in fake.commands)


def test_managed_launcher_binds_content_addressed_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_systemd(monkeypatch)
    identity = _identity(tmp_path)
    service.install_service(identity, start=False)
    digest = "a" * 64

    changed = service.refresh_installed_service_definition(identity, digest)

    assert changed is True
    launcher = service.launcher_path().read_text(encoding="utf-8")
    assert f"runtime_digest = {digest!r}" in launcher
    assert 'runtime_dir = data_dir / "runtimes" / runtime_digest' in launcher
    assert "WORKGATE_WORKER_RUNTIME_SHA256" in launcher
    assert 'runtime_dir = data_dir / "runtime"' not in launcher
    with pytest.raises(ValueError, match="runtime digest"):
        service._launcher_text("invalid")


def test_systemd_profile_rebind_updates_unit_workdir_and_reloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_systemd(monkeypatch)
    first = _profile_identity(
        tmp_path,
        monkeypatch,
        profile_id="p_abcdefgh",
        digest="a" * 64,
    )
    service.install_service(first, start=False)

    second_workdir = tmp_path / "second workdir"
    second_workdir.mkdir()
    second_profile = "p_ijklmnop"
    second_digest = "b" * 64
    second = {
        **first,
        "profile_id": second_profile,
        "workdir": str(second_workdir),
    }
    worker._write_worker_identity(second, second_profile)
    update_worker_profile(
        second_profile,
        runtime_sha256=second_digest,
        runtime_version="4.1.0",
        server=second["server"],
        name=second["name"],
        workdir=second["workdir"],
    )
    fake.commands.clear()

    changed = service.refresh_installed_service_definition(
        second,
        second_digest,
    )

    assert changed is True
    assert service.systemd_unit_path().read_text(encoding="utf-8") == (
        service.systemd_unit_text(str(second_workdir.resolve()))
    )
    launcher = service.launcher_path().read_text(encoding="utf-8")
    assert f"runtime_digest = {second_digest!r}" in launcher
    assert (
        f'"-m", "workgate.remote_worker", *["run", "{second_profile}"]'
        in launcher
    )
    assert ["/usr/bin/systemctl", "--user", "daemon-reload"] in fake.commands

    fake.commands.clear()
    assert (
        service.refresh_installed_service_definition(second, second_digest)
        is False
    )
    assert ["/usr/bin/systemctl", "--user", "daemon-reload"] in fake.commands


def test_launchd_running_start_is_noop_but_restart_kickstarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _configure_launchd(monkeypatch)
    service.install_service(_identity(tmp_path))
    fake.commands.clear()
    service.start_service()
    assert not any(
        command[1] in {"bootstrap", "kickstart"} for command in fake.commands
    )
    service.restart_service()
    assert any(command[1] == "kickstart" for command in fake.commands)


def test_private_log_missing_symlink_rotation_and_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = tmp_path / "worker.log"
    assert service._bounded_tail(path, 10) == ""
    target = tmp_path / "target.log"
    target.write_text("secret", encoding="utf-8")
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink unavailable")
    assert service._bounded_tail(path, 10) == ""
    path.unlink()
    path.write_text("old\n", encoding="utf-8")

    sleeps = 0

    def sleep(_delay: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            path.write_text("new\n", encoding="utf-8")
            return
        if sleeps == 2:
            with path.open("a", encoding="utf-8") as handle:
                handle.write("append\n")
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(service.time, "sleep", sleep)
    service._follow_private_log(path, 1)
    output = capsys.readouterr().out
    assert "old" in output
    assert "new" in output
    assert "append" in output


def test_log_tail_signature_detects_same_metadata_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = tmp_path / "worker.log"
    path.write_text("old\n", encoding="utf-8")
    original_stat = path.stat()
    real_stat = Path.stat
    sleeps = 0

    def stable_stat(candidate: Path, *args, **kwargs):
        info = real_stat(candidate, *args, **kwargs)
        if candidate == path:
            return SimpleNamespace(
                st_size=info.st_size,
                st_dev=original_stat.st_dev,
                st_ino=original_stat.st_ino,
                st_mtime_ns=original_stat.st_mtime_ns,
            )
        return info

    def sleep(_delay: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            path.write_text("new\n", encoding="utf-8")
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(Path, "stat", stable_stat)
    monkeypatch.setattr(service.time, "sleep", sleep)
    service._follow_private_log(path, 1)

    output = capsys.readouterr().out
    assert "old" in output
    assert "new" in output


def test_systemd_logs_nonfollow_follow_and_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake = _configure_systemd(monkeypatch)
    with pytest.raises(service.WorkerServiceError, match="not installed"):
        service.service_logs()

    service.systemd_unit_path().parent.mkdir(parents=True)
    service.systemd_unit_path().touch()
    fake.enabled = True
    fake.running = True

    def run(command, *, timeout=15):
        if command[0] == "/usr/bin/journalctl":
            return subprocess.CompletedProcess(command, 0, "journal-line\n", "")
        return fake.run(command, timeout=timeout)

    monkeypatch.setattr(service, "_run", run)
    service.service_logs(lines=3)
    assert capsys.readouterr().out == "journal-line\n"

    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda command, check=False: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    service.service_logs(lines=3, follow=True)


def test_cli_service_error_json_on_unsupported_windows(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        worker,
        "load_worker_identity",
        lambda: {"workdir": "/work"},
    )
    args = _build_parser().parse_args(["worker", "install-service"])
    with pytest.raises(SystemExit) as error:
        args.handler(args)
    assert error.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "schema_version": 1,
        "ok": False,
        "error": "WorkerServiceError",
    }


def test_update_no_change_does_not_restart(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        worker_cli,
        "_load_identity",
        lambda: {"server": "https://controller.test"},
    )
    monkeypatch.setattr(service, "service_status", _stopped_status)
    monkeypatch.setattr(
        runtime,
        "update_installed_runtime",
        lambda server, force=False: {
            "updated": False,
            "version": "4.0.0",
            "sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        service,
        "restart_service",
        lambda: pytest.fail("restarted unchanged runtime"),
    )
    refreshed: list[tuple[dict[str, str], str | None]] = []
    monkeypatch.setattr(
        service,
        "refresh_installed_service_definition",
        lambda identity, runtime_digest=None: (
            refreshed.append((identity, runtime_digest)) or False
        ),
    )
    worker_cli._update_from_args(argparse.Namespace(force=False))
    assert json.loads(capsys.readouterr().out)["service_restarted"] is False
    assert refreshed == [({"server": "https://controller.test"}, "a" * 64)]


def test_real_systemd_user_status_smoke_when_available(monkeypatch):
    if sys.platform != "linux" or service.shutil.which("systemctl") is None:
        pytest.skip("systemd user manager is unavailable on this platform")
    probe = subprocess.run(
        ["systemctl", "--user", "show-environment"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode != 0:
        pytest.skip("systemd user manager is unavailable in this session")
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    status = service.service_status()
    assert status.manager == "systemd"
    assert status.supported is True
    assert status.available is True
    assert status.state in {
        "not_installed",
        "stopped",
        "running",
        "failed",
        "unknown",
    }


def test_windows_install_reports_unsupported_before_identity_lookup(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(service.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        worker,
        "load_worker_identity",
        lambda: pytest.fail(
            "identity should not be loaded on unsupported platform"
        ),
    )
    args = _build_parser().parse_args(["worker", "install-service"])
    with pytest.raises(SystemExit) as error:
        args.handler(args)
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)["error"] == "WorkerServiceError"
