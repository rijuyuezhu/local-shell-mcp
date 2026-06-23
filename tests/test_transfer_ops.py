import io
import tarfile

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops.transfer import (
    transfer_abort_write,
    transfer_begin_write,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_chunk,
)
from local_shell_mcp.server.mcp.app import build_mcp


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    return tmp_path


def test_chunked_transfer_round_trip_and_checksum(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    data = bytes(range(256)) * 3000 + b"tail"
    (root / "source.bin").write_bytes(data)

    stat = transfer_stat("source.bin", sha256=True)
    assert stat.size is not None
    begin = transfer_begin_write(
        "nested/dest.bin", overwrite=True, expected_bytes=stat.size
    )

    offset = 0
    chunks = 0
    while offset < stat.size:
        chunk = transfer_read_chunk(
            "source.bin", offset=offset, chunk_size=10_000
        )
        transfer_write_chunk(
            "nested/dest.bin",
            begin.transfer_id,
            offset,
            chunk.data_b64,
            chunk.sha256,
        )
        offset += chunk.bytes
        chunks += 1

    finish = transfer_finish_write(
        "nested/dest.bin",
        begin.transfer_id,
        expected_bytes=stat.size,
        expected_sha256=stat.sha256,
    )

    assert chunks > 1
    assert finish.bytes == len(data)
    assert finish.sha256 == stat.sha256
    assert (root / "nested" / "dest.bin").read_bytes() == data


def test_transfer_rejects_bad_chunk_checksum_and_abort_removes_temp(
    tmp_path, monkeypatch
):
    root = _workspace(tmp_path, monkeypatch)
    (root / "source.txt").write_text("hello", encoding="utf-8")
    begin = transfer_begin_write("dest.txt", overwrite=True, expected_bytes=5)
    chunk = transfer_read_chunk("source.txt", offset=0, chunk_size=128)

    with pytest.raises(ValueError, match="chunk sha256 mismatch"):
        transfer_write_chunk(
            "dest.txt", begin.transfer_id, 0, chunk.data_b64, "0" * 64
        )

    abort = transfer_abort_write("dest.txt", begin.transfer_id)
    assert abort.deleted is True
    assert not any(root.glob(".dest.txt.local-shell-mcp-transfer-*.tmp"))
    assert not (root / "dest.txt").exists()


def test_directory_pack_and_unpack_preserves_nested_files(
    tmp_path, monkeypatch
):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src" / "sub").mkdir(parents=True)
    (root / "src" / "sub" / "file.txt").write_text("nested", encoding="utf-8")
    (root / "src" / "root.bin").write_bytes(b"\x00\x01")

    pack = transfer_pack_dir("src")
    unpack = transfer_unpack_archive(pack.archive_path, "dst", overwrite=True)

    assert unpack.entries >= 2
    assert (root / "dst" / "sub" / "file.txt").read_text(
        encoding="utf-8"
    ) == "nested"
    assert (root / "dst" / "root.bin").read_bytes() == b"\x00\x01"
    assert not (root / pack.archive_path).exists()


def test_unpack_rejects_archive_path_traversal(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    archive = root / "bad.tar"
    payload = b"bad"
    info = tarfile.TarInfo("../escape.txt")
    info.size = len(payload)
    with tarfile.open(archive, "w") as tar:
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="unsafe archive member path"):
        transfer_unpack_archive(
            "bad.tar", "dst", overwrite=True, cleanup_archive=False
        )

    assert not (root.parent / "escape.txt").exists()


@pytest.mark.asyncio
async def test_mcp_keeps_remote_transfer_behind_facade(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert "remote" in tools
    assert {
        "remote_copy_file",
        "remote_copy_dir",
        "remote_pull_file",
        "remote_push_file",
        "remote_pull_dir",
        "remote_push_dir",
    }.isdisjoint(tools)
    assert "transfer" in tools["remote"].inputSchema["properties"]["op"]["enum"]
