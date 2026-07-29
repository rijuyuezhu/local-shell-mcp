"""Internal POSIX runner that reaps descendants of one bounded command."""

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any

PR_SET_CHILD_SUBREAPER = 36
POLL_INTERVAL_S = 0.02
TERMINATE_GRACE_S = 1.0
KILL_GRACE_S = 1.0


def _shell_command_args(shell: str, command: str) -> list[str]:
    """Build native argv without importing the parent shell module."""
    name = os.path.basename(shell).lower()
    if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd", "cmd.exe"}:
        return [shell, "/D", "/S", "/C", command]
    return [shell, "-lc", command]


def _enable_child_subreaper() -> bool:
    """Make orphaned command descendants reparent to this runner on Linux."""
    if sys.platform != "linux":
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    except AttributeError, OSError:
        return False
    return result == 0


def _direct_children(pid: int) -> list[int]:
    """Return Linux procfs child pids for one process."""
    path = Path(f"/proc/{pid}/task/{pid}/children")
    try:
        raw = path.read_text(encoding="ascii").strip()
    except OSError:
        return []
    return [int(value) for value in raw.split() if value.isdigit()]


def _descendants(pid: int) -> list[int]:
    """Return all currently visible descendants, deepest children last."""
    found: list[int] = []
    pending = _direct_children(pid)
    seen: set[int] = set()
    while pending:
        child = pending.pop()
        if child in seen:
            continue
        seen.add(child)
        found.append(child)
        pending.extend(_direct_children(child))
    return found


def _signal_descendants(sig: signal.Signals) -> None:
    """Signal every process owned by this one-command runner."""
    for pid in reversed(_descendants(os.getpid())):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue


def _wait_for_no_descendants(timeout_s: float) -> bool:
    """Wait briefly for all command descendants to exit."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _reap_children()
        if not _descendants(os.getpid()):
            return True
        time.sleep(POLL_INTERVAL_S)
    _reap_children()
    return not _descendants(os.getpid())


def _reap_children() -> None:
    """Reap any exited descendants adopted through subreaper mode."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


def _cleanup_descendants() -> bool:
    """Terminate descendants left behind after a bounded command returns."""
    if not _descendants(os.getpid()):
        return True
    _signal_descendants(signal.SIGTERM)
    if _wait_for_no_descendants(TERMINATE_GRACE_S):
        _reap_children()
        return True
    _signal_descendants(signal.SIGKILL)
    cleaned = _wait_for_no_descendants(KILL_GRACE_S)
    _reap_children()
    return cleaned


def _mirror_signal(signum: int) -> int:
    """Exit through the same signal so the parent observes a negative code."""
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    return 128 + signum


def _handled_signals() -> tuple[signal.Signals, ...]:
    """Return only termination signals available on the current platform."""
    return tuple(
        handled
        for name in ("SIGINT", "SIGTERM", "SIGHUP")
        if (handled := getattr(signal, name, None)) is not None
    )


def run_bounded_command(shell: str, command: str) -> int:
    """Run one command and guarantee that surviving descendants are removed."""
    _enable_child_subreaper()
    received_signal = 0

    def remember_signal(signum: int, _frame: FrameType | None) -> None:
        nonlocal received_signal
        received_signal = received_signal or signum

    for handled in _handled_signals():
        signal.signal(handled, remember_signal)

    try:
        process = subprocess.Popen(_shell_command_args(shell, command))
    except FileNotFoundError as exc:
        print(
            f"Unable to start configured shell {shell!r}: {exc}",
            file=sys.stderr,
        )
        return 127

    while process.poll() is None and not received_signal:
        time.sleep(POLL_INTERVAL_S)

    if received_signal:
        _cleanup_descendants()
        return _mirror_signal(received_signal)

    returncode = process.wait()
    if not _cleanup_descendants():
        print(
            "Bounded command descendants did not exit after SIGKILL",
            file=sys.stderr,
        )
        return 125
    if returncode < 0:
        return _mirror_signal(-returncode)
    return returncode


def run_bounded_runner_from_args(args: argparse.Namespace) -> None:
    """Argparse handler for the private bounded-runner subcommand."""
    raise SystemExit(run_bounded_command(str(args.shell), str(args.command)))


def register_bounded_runner_cli(subparsers: Any) -> argparse.ArgumentParser:
    """Register the private bounded process runner."""
    parser = subparsers.add_parser(
        "bounded-runner",
        help="Run one bounded command and reap descendants (internal)",
        description="Run one bounded command and reap descendants. Internal interface.",
    )
    parser.add_argument("--shell", required=True)
    parser.add_argument("--command", required=True)
    parser.set_defaults(handler=run_bounded_runner_from_args)
    return parser


def main() -> None:
    """Run the lightweight module entry point without importing the server CLI."""
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp-bounded-runner",
        description="Run one bounded command and reap descendants.",
    )
    parser.add_argument("--shell", required=True)
    parser.add_argument("--command", required=True)
    run_bounded_runner_from_args(parser.parse_args())


if __name__ == "__main__":
    main()
