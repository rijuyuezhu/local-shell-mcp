import argparse
import signal
from types import SimpleNamespace

import pytest

from local_shell_mcp.ops.utils import bounded_runner


def test_shell_command_args_support_native_windows_shells():
    assert bounded_runner._shell_command_args("pwsh.exe", "echo ok") == [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "echo ok",
    ]
    assert bounded_runner._shell_command_args("cmd.exe", "echo ok") == [
        "cmd.exe",
        "/D",
        "/S",
        "/C",
        "echo ok",
    ]


def test_handled_signals_omit_platform_missing_sighup(monkeypatch):
    monkeypatch.delattr(bounded_runner.signal, "SIGHUP", raising=False)

    assert bounded_runner._handled_signals() == (
        signal.SIGINT,
        signal.SIGTERM,
    )


def test_enable_child_subreaper_is_disabled_off_linux(monkeypatch):
    monkeypatch.setattr(bounded_runner.sys, "platform", "win32")

    assert bounded_runner._enable_child_subreaper() is False


def test_enable_child_subreaper_handles_missing_prctl(monkeypatch):
    class MissingPrctl:
        def __getattr__(self, name):
            raise AttributeError(name)

    monkeypatch.setattr(bounded_runner.sys, "platform", "linux")
    monkeypatch.setattr(
        bounded_runner.ctypes, "CDLL", lambda *a, **k: MissingPrctl()
    )

    assert bounded_runner._enable_child_subreaper() is False


def test_process_tree_helpers_handle_races_and_cycles(monkeypatch):
    def fake_children(pid: int) -> list[int]:
        return {1: [2, 3], 2: [3], 3: [1]}.get(pid, [])

    monkeypatch.setattr(bounded_runner, "_direct_children", fake_children)

    assert set(bounded_runner._descendants(1)) == {1, 2, 3}


def test_signal_descendants_ignores_disappeared_and_forbidden_processes(
    monkeypatch,
):
    monkeypatch.setattr(bounded_runner, "_descendants", lambda _pid: [1, 2])

    def fake_kill(pid: int, _sig):
        if pid == 2:
            raise ProcessLookupError
        raise PermissionError

    monkeypatch.setattr(bounded_runner.os, "kill", fake_kill)

    bounded_runner._signal_descendants(signal.SIGTERM)


def test_cleanup_descendants_escalates_to_sigkill(monkeypatch):
    signals = []
    waits = iter([False, True])
    monkeypatch.setattr(bounded_runner, "_descendants", lambda _pid: [2])
    monkeypatch.setattr(
        bounded_runner, "_signal_descendants", lambda sig: signals.append(sig)
    )
    monkeypatch.setattr(
        bounded_runner, "_wait_for_no_descendants", lambda _timeout: next(waits)
    )
    monkeypatch.setattr(bounded_runner, "_reap_children", lambda: None)

    assert bounded_runner._cleanup_descendants() is True
    assert signals == [signal.SIGTERM, bounded_runner._force_kill_signal()]


def test_force_kill_signal_falls_back_to_sigterm(monkeypatch):
    monkeypatch.delattr(bounded_runner.signal, "SIGKILL", raising=False)

    assert bounded_runner._force_kill_signal() == signal.SIGTERM


def test_mirror_signal_resets_and_resends_signal(monkeypatch):
    calls = []
    monkeypatch.setattr(
        bounded_runner.signal,
        "signal",
        lambda signum, handler: calls.append((signum, handler)),
    )
    monkeypatch.setattr(
        bounded_runner.os,
        "kill",
        lambda pid, signum: calls.append((pid, signum)),
    )
    monkeypatch.setattr(bounded_runner.os, "getpid", lambda: 42)

    assert bounded_runner._mirror_signal(signal.SIGTERM) == 143
    assert calls == [
        (signal.SIGTERM, signal.SIG_DFL),
        (42, signal.SIGTERM),
    ]


def test_run_bounded_command_reports_missing_shell(capsys):
    assert (
        bounded_runner.run_bounded_command("/missing/shell", "echo ok") == 127
    )
    assert "Unable to start configured shell" in capsys.readouterr().err


def test_run_bounded_command_reports_cleanup_failure(monkeypatch, capsys):
    process = SimpleNamespace(poll=lambda: 0, wait=lambda: 0)
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args: process
    )
    monkeypatch.setattr(bounded_runner, "_cleanup_descendants", lambda: False)

    assert bounded_runner.run_bounded_command("sh", "true") == 125
    assert "did not exit after forced termination" in capsys.readouterr().err


def test_run_bounded_command_mirrors_child_signal(monkeypatch):
    process = SimpleNamespace(
        poll=lambda: -signal.SIGTERM, wait=lambda: -signal.SIGTERM
    )
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args: process
    )
    monkeypatch.setattr(bounded_runner, "_cleanup_descendants", lambda: True)
    monkeypatch.setattr(
        bounded_runner, "_mirror_signal", lambda signum: 128 + signum
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 143


def test_bounded_runner_argparse_handler_exits_with_result(monkeypatch):
    monkeypatch.setattr(
        bounded_runner, "run_bounded_command", lambda shell, command: 7
    )

    with pytest.raises(SystemExit, match="7"):
        bounded_runner.run_bounded_runner_from_args(
            argparse.Namespace(shell="sh", command="false")
        )
