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


def test_direct_children_parses_procfs_pids(monkeypatch):
    fake_path = SimpleNamespace(
        read_text=lambda *, encoding: "12 34 ignored 56\n"
    )
    monkeypatch.setattr(bounded_runner, "Path", lambda _path: fake_path)

    assert bounded_runner._direct_children(7) == [12, 34, 56]


def test_wait_for_no_descendants_reaps_until_empty(monkeypatch):
    descendants = iter([[3], []])
    reaped: list[bool] = []
    clock = iter([0.0, 0.1, 0.2])
    monkeypatch.setattr(bounded_runner.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        bounded_runner, "_descendants", lambda _pid: next(descendants)
    )
    monkeypatch.setattr(
        bounded_runner, "_reap_children", lambda: reaped.append(True)
    )
    monkeypatch.setattr(bounded_runner.time, "sleep", lambda _seconds: None)

    assert bounded_runner._wait_for_no_descendants(1.0) is True
    assert reaped == [True, True]


def test_reap_children_stops_when_no_child_is_ready(monkeypatch):
    results = iter([(10, 0), (0, 0)])
    monkeypatch.setattr(bounded_runner.os, "WNOHANG", 1, raising=False)
    monkeypatch.setattr(
        bounded_runner.os, "waitpid", lambda _pid, _flags: next(results)
    )

    bounded_runner._reap_children()


def test_reap_children_is_noop_without_nonblocking_wait(monkeypatch):
    monkeypatch.delattr(bounded_runner.os, "WNOHANG", raising=False)
    monkeypatch.setattr(
        bounded_runner.os,
        "waitpid",
        lambda *_args: pytest.fail("waitpid must not be called"),
        raising=False,
    )

    bounded_runner._reap_children()


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


def test_cleanup_descendants_returns_after_graceful_term(monkeypatch):
    signals = []
    monkeypatch.setattr(bounded_runner, "_descendants", lambda _pid: [2])
    monkeypatch.setattr(
        bounded_runner, "_signal_descendants", lambda sig: signals.append(sig)
    )
    monkeypatch.setattr(
        bounded_runner, "_wait_for_no_descendants", lambda _timeout: True
    )
    monkeypatch.setattr(bounded_runner, "_reap_children", lambda: None)

    assert bounded_runner._cleanup_descendants() is True
    assert signals == [signal.SIGTERM]


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


def test_run_bounded_command_mirrors_received_signal(monkeypatch):
    handlers = {}
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args: process
    )
    monkeypatch.setattr(
        bounded_runner, "_handled_signals", lambda: (signal.SIGTERM,)
    )
    monkeypatch.setattr(
        bounded_runner.signal,
        "signal",
        lambda signum, handler: handlers.setdefault(signum, handler),
    )
    monkeypatch.setattr(
        bounded_runner.time,
        "sleep",
        lambda _seconds: handlers[signal.SIGTERM](signal.SIGTERM, None),
    )
    monkeypatch.setattr(bounded_runner, "_cleanup_descendants", lambda: True)
    monkeypatch.setattr(
        bounded_runner, "_mirror_signal", lambda signum: 128 + signum
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 143


def test_run_bounded_command_returns_normal_exit_code(monkeypatch):
    process = SimpleNamespace(poll=lambda: 7, wait=lambda: 7)
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args: process
    )
    monkeypatch.setattr(bounded_runner, "_cleanup_descendants", lambda: True)

    assert bounded_runner.run_bounded_command("sh", "false") == 7


def test_bounded_runner_argparse_handler_exits_with_result(monkeypatch):
    monkeypatch.setattr(
        bounded_runner, "run_bounded_command", lambda shell, command: 7
    )

    with pytest.raises(SystemExit, match="7"):
        bounded_runner.run_bounded_runner_from_args(
            argparse.Namespace(shell="sh", command="false")
        )


def test_bounded_runner_main_parses_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        bounded_runner,
        "run_bounded_command",
        lambda shell, command: calls.append((shell, command)) or 4,
    )
    monkeypatch.setattr(
        bounded_runner.sys,
        "argv",
        ["bounded-runner", "--shell", "sh", "--command", "echo ok"],
    )

    with pytest.raises(SystemExit, match="4"):
        bounded_runner.main()

    assert calls == [("sh", "echo ok")]
