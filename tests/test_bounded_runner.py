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


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, True),
        (ProcessLookupError(), False),
        (PermissionError(), True),
    ],
)
def test_process_group_alive_handles_platform_results(
    error, expected, monkeypatch
):
    def fake_killpg(_pgid, _signal):
        if error is not None:
            raise error

    monkeypatch.setattr(bounded_runner.os, "killpg", fake_killpg, raising=False)

    assert bounded_runner._process_group_alive(42) is expected


@pytest.mark.parametrize(
    "error", [None, ProcessLookupError(), PermissionError()]
)
def test_signal_process_group_tolerates_exit_races(error, monkeypatch):
    calls = []

    def fake_killpg(pgid, sig):
        calls.append((pgid, sig))
        if error is not None:
            raise error

    monkeypatch.setattr(bounded_runner.os, "killpg", fake_killpg, raising=False)

    bounded_runner._signal_process_group(42, signal.SIGTERM)

    assert calls == [(42, signal.SIGTERM)]


def test_wait_for_process_group_exit_returns_early(monkeypatch):
    clock = iter([0.0, 0.1, 0.2])
    alive = iter([True, False])
    reaped = []
    monkeypatch.setattr(bounded_runner.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        bounded_runner, "_process_group_alive", lambda _pgid: next(alive)
    )
    monkeypatch.setattr(
        bounded_runner, "_reap_children", lambda: reaped.append(True)
    )
    monkeypatch.setattr(bounded_runner.time, "sleep", lambda _seconds: None)

    assert bounded_runner._wait_for_process_group_exit(42, 1.0) is True
    assert reaped == [True, True]


def test_wait_for_process_group_exit_reports_timeout(monkeypatch):
    clock = iter([0.0, 0.5, 1.0])
    reaped = []
    monkeypatch.setattr(bounded_runner.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        bounded_runner, "_process_group_alive", lambda _pgid: True
    )
    monkeypatch.setattr(
        bounded_runner, "_reap_children", lambda: reaped.append(True)
    )
    monkeypatch.setattr(bounded_runner.time, "sleep", lambda _seconds: None)

    assert bounded_runner._wait_for_process_group_exit(42, 1.0) is False
    assert reaped == [True, True]


def test_cleanup_process_group_returns_when_already_gone(monkeypatch):
    monkeypatch.setattr(
        bounded_runner, "_process_group_alive", lambda _pgid: False
    )
    monkeypatch.setattr(
        bounded_runner,
        "_signal_process_group",
        lambda *_args: pytest.fail("no signal is needed"),
    )

    assert bounded_runner._cleanup_process_group(42) is True


def test_cleanup_process_group_escalates_after_term_timeout(monkeypatch):
    signals = []
    waits = iter([False, True])
    monkeypatch.setattr(
        bounded_runner, "_process_group_alive", lambda _pgid: True
    )
    monkeypatch.setattr(
        bounded_runner,
        "_signal_process_group",
        lambda pgid, sig: signals.append((pgid, sig)),
    )
    monkeypatch.setattr(
        bounded_runner,
        "_wait_for_process_group_exit",
        lambda _pgid, _timeout: next(waits),
    )

    assert bounded_runner._cleanup_process_group(42) is True
    assert signals == [
        (42, signal.SIGTERM),
        (42, bounded_runner._force_kill_signal()),
    ]


def test_cleanup_command_processes_rechecks_group_after_reaping(monkeypatch):
    waits = []
    monkeypatch.setattr(
        bounded_runner, "_cleanup_process_group", lambda _pgid: False
    )
    monkeypatch.setattr(bounded_runner, "_cleanup_descendants", lambda: True)
    monkeypatch.setattr(
        bounded_runner,
        "_wait_for_process_group_exit",
        lambda pgid, timeout: waits.append((pgid, timeout)) or True,
    )

    assert (
        bounded_runner._cleanup_command_processes(42, track_descendants=True)
        is True
    )
    assert waits == [(42, bounded_runner.POLL_INTERVAL_S * 5)]


def test_cleanup_command_processes_reports_descendant_failure(monkeypatch):
    monkeypatch.setattr(bounded_runner, "_cleanup_descendants", lambda: False)

    assert (
        bounded_runner._cleanup_command_processes(None, track_descendants=True)
        is False
    )


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


def test_run_bounded_command_reports_missing_shell(monkeypatch, capsys):
    monkeypatch.setattr(bounded_runner, "_enable_child_subreaper", lambda: True)
    assert (
        bounded_runner.run_bounded_command("/missing/shell", "echo ok") == 127
    )
    assert "Unable to start configured shell" in capsys.readouterr().err


def test_run_bounded_command_reports_cleanup_failure(monkeypatch, capsys):
    monkeypatch.setattr(bounded_runner, "_enable_child_subreaper", lambda: True)
    process = SimpleNamespace(pid=42, poll=lambda: 0, wait=lambda: 0)
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args, **_kwargs: process
    )
    monkeypatch.setattr(
        bounded_runner,
        "_cleanup_command_processes",
        lambda _pgid, *, track_descendants: False,
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 125
    assert "did not exit after forced termination" in capsys.readouterr().err


def test_run_bounded_command_mirrors_child_signal(monkeypatch):
    monkeypatch.setattr(bounded_runner, "_enable_child_subreaper", lambda: True)
    process = SimpleNamespace(
        pid=42,
        poll=lambda: -signal.SIGTERM,
        wait=lambda: -signal.SIGTERM,
    )
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args, **_kwargs: process
    )
    monkeypatch.setattr(
        bounded_runner,
        "_cleanup_command_processes",
        lambda _pgid, *, track_descendants: True,
    )
    monkeypatch.setattr(
        bounded_runner, "_mirror_signal", lambda signum: 128 + signum
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 143


def test_run_bounded_command_mirrors_received_signal(monkeypatch):
    monkeypatch.setattr(bounded_runner, "_enable_child_subreaper", lambda: True)
    handlers = {}
    process = SimpleNamespace(pid=42, poll=lambda: None)
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args, **_kwargs: process
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
    monkeypatch.setattr(
        bounded_runner,
        "_cleanup_command_processes",
        lambda _pgid, *, track_descendants: True,
    )
    monkeypatch.setattr(
        bounded_runner, "_mirror_signal", lambda signum: 128 + signum
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 143


def test_run_bounded_command_returns_normal_exit_code(monkeypatch):
    monkeypatch.setattr(bounded_runner, "_enable_child_subreaper", lambda: True)
    process = SimpleNamespace(pid=42, poll=lambda: 7, wait=lambda: 7)
    monkeypatch.setattr(
        bounded_runner.subprocess, "Popen", lambda _args, **_kwargs: process
    )
    monkeypatch.setattr(
        bounded_runner,
        "_cleanup_command_processes",
        lambda _pgid, *, track_descendants: True,
    )

    assert bounded_runner.run_bounded_command("sh", "false") == 7


def test_run_bounded_command_fails_closed_without_containment(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        bounded_runner, "_enable_child_subreaper", lambda: False
    )
    monkeypatch.setattr(
        bounded_runner, "_process_group_containment_available", lambda: False
    )
    monkeypatch.setattr(
        bounded_runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("command must not start"),
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 125
    assert "containment is unavailable" in capsys.readouterr().err


def test_run_bounded_command_uses_process_group_fallback(monkeypatch):
    calls = []
    process = SimpleNamespace(pid=42, poll=lambda: 0, wait=lambda: 0)
    monkeypatch.setattr(
        bounded_runner, "_enable_child_subreaper", lambda: False
    )
    monkeypatch.setattr(
        bounded_runner, "_process_group_containment_available", lambda: True
    )

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(bounded_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        bounded_runner,
        "_cleanup_command_processes",
        lambda pgid, *, track_descendants: (
            calls.append((pgid, track_descendants)) or True
        ),
    )

    assert bounded_runner.run_bounded_command("sh", "true") == 0
    assert calls[0][1]["start_new_session"] is True
    assert calls[1] == (42, False)


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
