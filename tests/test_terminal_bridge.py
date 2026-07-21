import base64
import os
import shutil
import subprocess
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

import local_shell_mcp.terminal_bridge as bridge_module
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.terminal_bridge import (
    TERMINAL_BRIDGE_BACKEND,
    TerminalBridgeBusyError,
    TerminalBridgeNotFoundError,
    close_terminal_bridge_execute,
    open_terminal_bridge_execute,
    read_terminal_bridge_execute,
    reset_terminal_bridges_for_tests,
    resize_terminal_bridge_execute,
    write_terminal_bridge_execute,
)


@pytest.fixture(autouse=True)
def _reset_bridges(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S", "60")
    clear_settings_cache()
    reset_terminal_bridges_for_tests()
    yield
    reset_terminal_bridges_for_tests()
    clear_settings_cache()


def test_terminal_bridge_orphan_lease_is_bounded(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S", "0")
    clear_settings_cache()
    assert bridge_module._idle_timeout_s() == 300

    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S", "1200")
    clear_settings_cache()
    assert bridge_module._idle_timeout_s() == 300


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY bridge")
def test_terminal_bridge_retries_short_and_blocked_writes(monkeypatch):
    attach = object.__new__(bridge_module._UnixTmuxAttach)
    attach._closed = False
    attach.master_fd = 7
    attach._write_lock = threading.Lock()
    cast(Any, attach).process = SimpleNamespace(poll=lambda: None)

    attempts = []
    outcomes = [BlockingIOError(), 2, 3]

    def fake_write(fd, data):
        attempts.append((fd, bytes(data)))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    waits = []

    def fake_select(readable, writable, exceptional, timeout):
        waits.append((readable, writable, exceptional, timeout))
        return [], writable, []

    monkeypatch.setattr(bridge_module.os, "write", fake_write)
    monkeypatch.setattr(bridge_module.select, "select", fake_select)

    attach.write_all(b"abcde")

    assert attempts == [(7, b"abcde"), (7, b"abcde"), (7, b"cde")]
    assert waits == [([], [7], [], 0.1)]
    assert outcomes == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY bridge")
@pytest.mark.asyncio
async def test_terminal_bridge_registry_bounds_and_lifecycle(monkeypatch):
    instances = []

    class FakeAttach:
        def __init__(self, shell_id, cols, rows):
            self.shell_id = shell_id
            self.cols = cols
            self.rows = rows
            self.closed = False
            self.writes = []
            self.reads = [(b"\x1b[31mready\x1b[0m", False), (b"", False)]
            instances.append(self)

        def read_wait(self, max_bytes, wait_ms):
            assert 1 <= max_bytes <= 65_536
            assert 0 <= wait_ms <= 1_000
            return self.reads.pop(0)

        def write_all(self, data):
            self.writes.append(bytes(data))

        def resize(self, cols, rows):
            self.cols = cols
            self.rows = rows

        def close_sync(self):
            self.closed = True

    monkeypatch.setattr(bridge_module, "_UnixTmuxAttach", FakeAttach)

    opened = await open_terminal_bridge_execute("demo", 100, 30)
    bridge_id = opened["bridge_id"]
    assert opened == {
        "bridge_id": bridge_id,
        "shell_id": "demo",
        "cols": 100,
        "rows": 30,
        "backend": TERMINAL_BRIDGE_BACKEND,
    }

    with pytest.raises(TerminalBridgeBusyError, match="already has"):
        await open_terminal_bridge_execute("demo", 80, 24)

    read = await read_terminal_bridge_execute(bridge_id, 1024, 25)
    assert base64.b64decode(read["data_b64"]) == b"\x1b[31mready\x1b[0m"
    assert read["bytes"] == 14
    assert read["eof"] is False

    payload = b"echo \xff\x00\r"
    written = await write_terminal_bridge_execute(
        bridge_id,
        base64.b64encode(payload).decode("ascii"),
    )
    assert written == {"bridge_id": bridge_id, "written_bytes": len(payload)}
    assert instances[0].writes == [payload]

    resized = await resize_terminal_bridge_execute(bridge_id, 132, 41)
    assert resized == {
        "bridge_id": bridge_id,
        "cols": 132,
        "rows": 41,
        "resized": True,
        "backend": TERMINAL_BRIDGE_BACKEND,
    }
    assert (instances[0].cols, instances[0].rows) == (132, 41)

    assert await close_terminal_bridge_execute(bridge_id) == {
        "bridge_id": bridge_id,
        "closed": True,
    }
    assert instances[0].closed is True
    assert await close_terminal_bridge_execute(bridge_id) == {
        "bridge_id": bridge_id,
        "closed": False,
    }
    with pytest.raises(TerminalBridgeNotFoundError):
        await read_terminal_bridge_execute(bridge_id)


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY bridge")
@pytest.mark.asyncio
async def test_terminal_bridge_rejects_malformed_capabilities_and_chunks(
    monkeypatch,
):
    class FakeAttach:
        def __init__(self, shell_id, cols, rows):
            self.closed = False

        def close_sync(self):
            self.closed = True

    monkeypatch.setattr(bridge_module, "_UnixTmuxAttach", FakeAttach)
    opened = await open_terminal_bridge_execute("demo", 80, 24)

    with pytest.raises(TerminalBridgeNotFoundError):
        await read_terminal_bridge_execute("../bad")
    with pytest.raises(ValueError, match="valid base64"):
        await write_terminal_bridge_execute(opened["bridge_id"], "not base64!")
    with pytest.raises(ValueError, match="too large"):
        await write_terminal_bridge_execute(
            opened["bridge_id"],
            base64.b64encode(b"x" * 65_537).decode("ascii"),
        )
    with pytest.raises(ValueError, match="cols must be between"):
        await resize_terminal_bridge_execute(opened["bridge_id"], 2, 24)


@pytest.mark.skipif(
    os.name == "nt"
    or shutil.which("tmux") is None
    or shutil.which("bash") is None,
    reason="requires POSIX tmux and bash",
)
@pytest.mark.asyncio
async def test_real_terminal_bridge_streams_raw_bytes_and_preserves_tmux_session(
    monkeypatch,
):
    shell_id = f"lsm-bridge-{uuid.uuid4().hex[:10]}"
    tmux = shutil.which("tmux") or "tmux"
    monkeypatch.setenv("LOCAL_SHELL_MCP_TMUX_BIN", tmux)
    clear_settings_cache()
    subprocess.run(
        [
            tmux,
            "new-session",
            "-d",
            "-s",
            shell_id,
            "bash",
            "--noprofile",
            "--norc",
        ],
        check=True,
    )
    bridge_id = ""
    try:
        opened = await open_terminal_bridge_execute(shell_id, 90, 28)
        bridge_id = opened["bridge_id"]
        command = b"printf '\\033[31mBRIDGE_RAW_OK\\033[0m\\n'\r"
        await write_terminal_bridge_execute(
            bridge_id,
            base64.b64encode(command).decode("ascii"),
        )

        deadline = time.monotonic() + 4
        output = bytearray()
        while (
            time.monotonic() < deadline
            and b"\x1b[31mBRIDGE_RAW_OK" not in output
        ):
            chunk = await read_terminal_bridge_execute(bridge_id, 65_536, 100)
            output.extend(base64.b64decode(chunk["data_b64"]))
            if chunk["eof"]:
                break
        assert b"\x1b[31mBRIDGE_RAW_OK" in output

        await resize_terminal_bridge_execute(bridge_id, 120, 35)
        await close_terminal_bridge_execute(bridge_id)
        bridge_id = ""
        assert (
            subprocess.run(
                [tmux, "has-session", "-t", shell_id],
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )
    finally:
        if bridge_id:
            await close_terminal_bridge_execute(bridge_id)
        subprocess.run(
            [tmux, "kill-session", "-t", shell_id],
            check=False,
            capture_output=True,
        )
