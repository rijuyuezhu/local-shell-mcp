import asyncio
import threading
import time
from pathlib import Path

import pytest

import local_shell_mcp.ops.shell as shell_ops
import local_shell_mcp.terminal.conpty as conpty
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)


class FakePty:
    def __init__(self) -> None:
        self._alive = True
        self._condition = threading.Condition()
        self._chunks: list[str | bytes] = []
        self.closed = False
        self.close_calls: list[bool] = []
        self.writes: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.write_result: int | None = None
        self.write_errors: list[BaseException] = []

    def isalive(self) -> bool:
        return self._alive

    def read(self, size: int | None = None) -> str | bytes:
        with self._condition:
            if not self._chunks and self._alive:
                self._condition.wait(0.05)
            if self._chunks:
                return self._chunks.pop(0)
            return ""

    def feed(self, value: str | bytes) -> None:
        with self._condition:
            self._chunks.append(value)
            self._condition.notify_all()

    def write(self, value: str) -> int | None:
        if self.write_errors:
            raise self.write_errors.pop(0)
        self.writes.append(value)
        return self.write_result

    def setwinsize(self, rows: int, cols: int) -> None:
        self.sizes.append((rows, cols))

    def close(self, force: bool = False) -> None:
        self.close_calls.append(force)
        self.closed = True
        self._alive = False
        with self._condition:
            self._condition.notify_all()


class FakePtyWithoutResize:
    def __init__(self) -> None:
        self._alive = True
        self.closed = False
        self.writes: list[str] = []

    def isalive(self) -> bool:
        return self._alive

    def read(self, size: int | None = None) -> str:
        time.sleep(0.01)
        return ""

    def write(self, value: str) -> None:
        self.writes.append(value)

    def close(self, force: bool = False) -> None:
        self.closed = True
        self._alive = False


@pytest.fixture(autouse=True)
def _reset_conpty(monkeypatch):
    conpty.reset_conpty_sessions_for_tests()
    monkeypatch.setattr(conpty, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(conpty, "relative_display", lambda path: str(path))
    monkeypatch.setattr(conpty, "is_available", lambda: True)
    monkeypatch.setattr(conpty, "_shell_executable", lambda: "cmd.exe")
    yield
    conpty.reset_conpty_sessions_for_tests()


async def _wait_for_output(shell_id: str, marker: bytes) -> bytes:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        session = conpty._get_session(shell_id)
        output = session.output_snapshot()
        if marker in output:
            return output
        await asyncio.sleep(0.01)
    raise AssertionError(f"ConPTY output did not contain {marker!r}")


@pytest.mark.asyncio
async def test_conpty_persistent_shell_and_raw_attachment(
    monkeypatch, tmp_path
):
    process = FakePty()
    spawned: list[tuple[list[str], Path, int, int]] = []

    def spawn(argv, cwd, cols, rows):
        spawned.append((list(argv), cwd, cols, rows))
        return process

    monkeypatch.setattr(conpty, "_spawn_pty", spawn)

    started = await conpty.start_shell(
        shell_id="demo",
        cwd=tmp_path,
        command=None,
    )
    assert started.shell_id == "demo"
    assert started.command == "cmd.exe"
    assert started.backend == "conpty"
    assert spawned == [
        (
            ["cmd.exe"],
            tmp_path,
            conpty.CONPTY_DEFAULT_COLUMNS,
            conpty.CONPTY_DEFAULT_ROWS,
        )
    ]

    process.feed("\x1b[31mready\x1b[0m\r\n")
    await _wait_for_output("demo", b"ready")

    plain = await conpty.read_shell("demo", 20, preserve_ansi=False)
    styled = await conpty.read_shell("demo", 20, preserve_ansi=True)
    assert plain.backend == "conpty"
    assert "ready" in plain.output
    assert "\x1b[31m" not in plain.output
    assert "\x1b[31mready" in styled.output

    sent = await conpty.send_shell("demo", "echo hello", True)
    assert sent.sent_bytes == len(b"echo hello")
    assert process.writes[-1] == "echo hello\r"

    resized = await conpty.resize_shell("demo", 132, 41)
    assert resized.resized is True
    assert resized.backend == "conpty"
    assert process.sizes[-1] == (41, 132)

    attachment = conpty.open_raw_attachment("demo", "bridge-one", 100, 30)
    history, eof = attachment.read_wait(65_536, 0)
    assert b"\x1b[31mready" in history
    assert eof is False

    process.feed(b"future-output")
    raw, eof = await asyncio.to_thread(attachment.read_wait, 65_536, 500)
    assert raw == b"future-output"
    assert eof is False

    before = len(process.writes)
    encoded = "你".encode()
    attachment.write_all(encoded[:1])
    assert len(process.writes) == before
    process.write_result = 0
    attachment.write_all(encoded[1:])
    assert process.writes[-1] == "你"

    attachment.close_sync()
    listed = await conpty.list_shells()
    assert [item.shell_id for item in listed.shells] == ["demo"]
    assert listed.shells[0].backend == "conpty"
    assert listed.shells[0].model_extra is not None
    assert listed.shells[0].model_extra["attached"] == "0"

    killed = await conpty.kill_shell("demo")
    assert killed.killed is True
    assert killed.backend == "conpty"
    assert process.close_calls[-1] is True
    assert (await conpty.list_shells()).shells == []


@pytest.mark.asyncio
async def test_conpty_reports_unsupported_resize_without_closing(
    monkeypatch, tmp_path
):
    process = FakePtyWithoutResize()
    monkeypatch.setattr(conpty, "_spawn_pty", lambda *args: process)

    await conpty.start_shell(shell_id="no-resize", cwd=tmp_path, command=None)
    resized = await conpty.resize_shell("no-resize", 100, 30)
    assert resized.resized is False

    attachment = conpty.open_raw_attachment(
        "no-resize", "bridge-no-resize", 100, 30
    )
    assert attachment.resize(120, 40) is False
    attachment.close_sync()
    assert conpty.has_session("no-resize") is True


@pytest.mark.asyncio
async def test_conpty_retries_blocked_writes_and_accepts_queued_zero(
    monkeypatch, tmp_path
):
    process = FakePty()
    process.write_errors = [BlockingIOError(), BlockingIOError()]
    process.write_result = 0
    monkeypatch.setattr(conpty, "_spawn_pty", lambda *args: process)
    monkeypatch.setattr(conpty.time, "sleep", lambda value: None)

    await conpty.start_shell(shell_id="writes", cwd=tmp_path, command=None)
    await conpty.send_shell("writes", "queued", False)
    assert process.writes == ["queued"]
    assert process.write_errors == []


def test_conpty_cleanup_reopens_closed_pywinpty_handle():
    observed: list[tuple[bool, bool]] = []

    class ClosedProcess:
        closed = True

        def close(self, force=False):
            observed.append((self.closed, force))

    process = ClosedProcess()
    conpty._close_pty_process(process, True)
    assert observed == [(False, True)]


def test_conpty_plain_text_strips_incomplete_controls():
    assert (
        conpty._strip_terminal_controls(
            "plain\x1b[31mred\x1b[0m\x1b\x01\x7f\tkept"
        )
        == "plainred\tkept"
    )


@pytest.mark.asyncio
async def test_conpty_reader_start_failure_closes_process(
    monkeypatch, tmp_path
):
    process = FakePty()
    monkeypatch.setattr(conpty, "_spawn_pty", lambda *args: process)
    monkeypatch.setattr(
        conpty._ConPtySession,
        "start_reader",
        lambda self: (_ for _ in ()).throw(RuntimeError("thread failed")),
    )

    with pytest.raises(RuntimeError, match="thread failed"):
        await conpty.start_shell(
            shell_id="reader-start-failure",
            cwd=tmp_path,
            command=None,
        )

    assert conpty.has_session("reader-start-failure") is False
    assert process.closed is True
    assert process.close_calls[-1] is True


@pytest.mark.asyncio
async def test_conpty_reader_failure_reaps_session(monkeypatch, tmp_path):
    class FailingPty(FakePty):
        def read(self, size: int | None = None) -> str:
            raise OSError("reader failed")

    process = FailingPty()
    monkeypatch.setattr(conpty, "_spawn_pty", lambda *args: process)

    await conpty.start_shell(
        shell_id="reader-failure", cwd=tmp_path, command=None
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and conpty.has_session("reader-failure"):
        await asyncio.sleep(0.01)

    assert conpty.has_session("reader-failure") is False
    assert process.closed is True
    assert process.close_calls[-1] is True


def test_conpty_raw_subscriber_overflow_finishes_stream(monkeypatch):
    monkeypatch.setattr(conpty, "CONPTY_RAW_BUFFER_BYTES", 4)
    subscriber = conpty._RawSubscriber(b"")
    subscriber.feed(b"abcdef")
    data, eof = subscriber.read_wait(10, 0)
    assert data == b"cdef"
    assert eof is True


def test_conpty_shell_argument_rendering(monkeypatch):
    monkeypatch.setattr(conpty, "_shell_executable", lambda: "cmd.exe")
    assert conpty._persistent_shell_args(None) == ["cmd.exe"]
    assert conpty._persistent_shell_args("echo hello") == [
        "cmd.exe",
        "/S",
        "/C",
        "echo hello",
    ]

    monkeypatch.setattr(conpty, "_shell_executable", lambda: "pwsh.exe")
    assert conpty._persistent_shell_args("Write-Output hello") == [
        "pwsh.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Write-Output hello",
    ]


@pytest.mark.asyncio
async def test_shell_ops_delegate_persistent_shells_to_conpty(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    monkeypatch.setattr(
        shell_ops, "_use_conpty_persistent_shell_backend", lambda: True
    )
    monkeypatch.setattr(conpty, "is_available", lambda: True)
    monkeypatch.setattr(
        conpty, "initial_command", lambda command: command or "cmd.exe"
    )

    calls: list[tuple[str, tuple, dict]] = []

    async def fake_list():
        calls.append(("list", (), {}))
        return ListPersistentShellsOutput(shells=[])

    async def fake_start(**kwargs):
        calls.append(("start", (), dict(kwargs)))
        return StartPersistentShellOutput(
            shell_id=kwargs["shell_id"],
            cwd=str(kwargs["cwd"]),
            command=kwargs["command"] or "cmd.exe",
            backend="conpty",
        )

    async def fake_send(shell_id, input_text, enter):
        calls.append(("send", (shell_id, input_text, enter), {}))
        return SendPersistentShellInputOutput(
            shell_id=shell_id,
            sent_bytes=len(input_text.encode()),
            enter=enter,
        )

    async def fake_resize(shell_id, cols, rows):
        calls.append(("resize", (shell_id, cols, rows), {}))
        return ResizePersistentShellOutput(
            shell_id=shell_id,
            cols=cols,
            rows=rows,
            resized=False,
            backend="conpty",
        )

    async def fake_read(shell_id, lines, *, preserve_ansi):
        calls.append(
            ("read", (shell_id, lines), {"preserve_ansi": preserve_ansi})
        )
        return ReadPersistentShellOutput(
            shell_id=shell_id,
            output="windows output",
            lines=lines,
            backend="conpty",
        )

    async def fake_kill(shell_id):
        calls.append(("kill", (shell_id,), {}))
        return KillPersistentShellOutput(
            shell_id=shell_id,
            killed=True,
            stderr="",
            backend="conpty",
        )

    monkeypatch.setattr(conpty, "list_shells", fake_list)
    monkeypatch.setattr(conpty, "start_shell", fake_start)
    monkeypatch.setattr(conpty, "send_shell", fake_send)
    monkeypatch.setattr(conpty, "resize_shell", fake_resize)
    monkeypatch.setattr(conpty, "read_shell", fake_read)
    monkeypatch.setattr(conpty, "kill_shell", fake_kill)

    started = await shell_ops.start_persistent_shell_execute(
        cwd=".",
        name="windows-demo",
        command=None,
        owner_session_id="SESSION1",
    )
    assert started.backend == "conpty"
    await shell_ops.send_persistent_shell_input_execute(
        "windows-demo", "echo hello", False
    )
    resized = await shell_ops.resize_persistent_shell_execute(
        "windows-demo", 120, 40
    )
    read = await shell_ops.read_persistent_shell_output_execute(
        "windows-demo", 50, preserve_ansi=True
    )
    killed = await shell_ops.kill_persistent_shell_execute("windows-demo")

    assert resized.resized is False
    assert read.output == "windows output"
    assert killed.killed is True
    assert [name for name, _, _ in calls] == [
        "list",
        "start",
        "send",
        "resize",
        "read",
        "kill",
    ]
    start_kwargs = calls[1][2]
    assert start_kwargs["shell_id"] == "windows-demo"
    assert start_kwargs["cwd"] == tmp_path
    assert start_kwargs["command"] is None
    assert start_kwargs["owner_session_id"] == "SESSION1"
    clear_settings_cache()
