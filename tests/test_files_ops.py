import json
from pathlib import Path

import pytest

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.files import (
    edit_file_execute,
    edit_lines_execute,
    list_files_execute,
    multi_edit_file_execute,
    read_file_execute,
    read_many_files_execute,
    write_file_execute,
)
from local_shell_mcp.ops.shell import check_command_policy
from local_shell_mcp.ops.utils.path import resolve_path
from local_shell_mcp.schemas.input_models.files import ReadFileRequest
from local_shell_mcp.server.mcp.app import build_mcp
from tests.helpers import nested_mcp_text


def test_write_read_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    write_file_execute("a.txt", "hello world")
    assert read_file_execute("a.txt").content == "hello world"
    edit_file_execute("a.txt", "world", "mcp")
    assert read_file_execute("a.txt").content == "hello mcp"


def test_list_files_reports_limit_and_truncation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    listed_dir = tmp_path / "listed"
    listed_dir.mkdir()
    (listed_dir / "a.txt").write_text("a", encoding="utf-8")
    (listed_dir / "b.txt").write_text("b", encoding="utf-8")

    limited = list_files_execute("listed", max_entries=1)
    complete = list_files_execute("listed", max_entries=10)

    assert limited.limit_count == 1
    assert limited.count == 1
    assert limited.is_truncated is True
    assert len(limited.entries) == 1
    assert "total_count" not in limited.model_dump()

    assert complete.count == 2
    assert complete.is_truncated is False


def test_read_text_rejects_invalid_utf8(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "invalid.bin").write_bytes(b"\xff\xfe\xfd")

    with pytest.raises(UnicodeDecodeError):
        read_file_execute("invalid.bin")


def test_read_text_allows_valid_utf8_control_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "nul.txt").write_bytes(b"abc\x00def")

    result = read_file_execute("nul.txt")

    assert result.content == "abc\x00def"


def test_read_text_returns_line_numbers_and_snapshot_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "lines.txt").write_text(
        "alpha\nbeta\ngamma\n", encoding="utf-8"
    )

    result = read_file_execute("lines.txt", start_line=2, end_line=3)

    assert result.content == "beta\ngamma"
    assert result.start_line == 2
    assert result.end_line == 3
    assert result.line_count == 2
    assert result.lines[0].line == 2
    assert result.lines[0].text == "beta"
    assert result.numbered_content == "2|beta\n3|gamma"
    assert result.session_id == "default"
    assert result.snapshot_id
    assert result.file_sha256
    assert [item.model_dump() for item in result.seen_ranges] == [
        {"start": 2, "end": 3}
    ]


def test_read_text_reports_original_size_and_truncation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "5")
    clear_settings_cache()
    (tmp_path / "long.txt").write_text("hello world", encoding="utf-8")

    result = read_file_execute("long.txt")

    assert result.bytes == 11
    assert result.bytes_read == 5
    assert result.truncated_bytes == 6
    assert result.truncated is True
    assert result.content == "hello"
    assert result.numbered_content == "1|hello"


def test_write_text_does_not_read_existing_file_before_overwrite(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")

    def fail_read_text(self, *args, **kwargs):
        raise AssertionError(
            "write_file_execute should not read old file contents"
        )

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    result = write_file_execute("existing.txt", "new")

    assert result.created is False
    assert (tmp_path / "existing.txt").read_bytes().decode("utf-8") == "new"


def test_edit_refuses_files_above_write_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "5")
    clear_settings_cache()
    (tmp_path / "large.txt").write_text("hello world", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to edit"):
        edit_file_execute("large.txt", "world", "mcp")


def test_edits_reject_invalid_utf8_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    original = b"abc\xffworld"
    (tmp_path / "blob.bin").write_bytes(original)

    with pytest.raises(UnicodeDecodeError):
        edit_file_execute("blob.bin", "world", "mcp")
    with pytest.raises(UnicodeDecodeError):
        multi_edit_file_execute("blob.bin", [{"old": "world", "new": "mcp"}])

    assert (tmp_path / "blob.bin").read_bytes() == original


@pytest.mark.asyncio
async def test_fetch_reports_non_utf8_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "blob.bin").write_bytes(b"abc\xffworld")

    response = await build_mcp().call_tool("fetch", {"id": "blob.bin"})
    payload = json.loads(nested_mcp_text(response))

    assert payload["text"].startswith(
        "Unable to fetch file: UnicodeDecodeError:"
    )
    assert payload["metadata"]["error"] == "UnicodeDecodeError"


def test_read_many_files_supports_per_file_line_ranges(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "a.txt").write_text("a1\na2\na3\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b1\nb2\nb3\n", encoding="utf-8")

    result = read_many_files_execute(
        [
            ("a.txt", 2, 2),
            ReadFileRequest(path="b.txt", start_line=1, end_line=2),
        ]
    )

    assert [item.content for item in result.files] == ["a2", "b1\nb2"]
    assert result.total_content_bytes == len(b"a2b1\nb2")


def test_read_many_files_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_READ_MANY_FILES", "1")
    clear_settings_cache()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to read 2 files; max is 1"):
        read_many_files_execute([("a.txt", None, None), ("b.txt", None, None)])


def test_reject_path_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "false")
    clear_settings_cache()
    with pytest.raises(ValueError):
        resolve_path("/etc/passwd")


def test_full_container_mode_disables_builtin_restrictions(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "true")
    clear_settings_cache()

    settings = get_settings()
    assert settings.command_denylist == []
    assert settings.path_denylist == []
    assert str(resolve_path("/etc/passwd")) == "/etc/passwd"
    check_command_policy("mount /dev/null /mnt || true")


def test_read_text_handles_truncated_utf8_sequence(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "4")
    clear_settings_cache()
    (tmp_path / "utf8.txt").write_text("你好", encoding="utf-8")

    result = read_file_execute("utf8.txt")

    assert result.truncated is True
    assert result.bytes_read == 4
    assert result.content == "你"


def test_parse_read_target_supports_line_and_raw_selectors():
    from local_shell_mcp.tool_session.selectors import parse_read_target

    assert parse_read_target("src/foo.py:50-80").path == "src/foo.py"
    ranged = parse_read_target("src/foo.py:50+20:raw")
    assert ranged.path == "src/foo.py"
    assert ranged.start_line == 50
    assert ranged.end_line == 69
    assert ranged.raw is True
    raw_first = parse_read_target("src/foo.py:raw:10-12")
    assert raw_first.start_line == 10
    assert raw_first.end_line == 12
    assert raw_first.raw is True


def test_edit_lines_uses_snapshot_and_returns_diff_context(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text(
        "alpha\nbeta\ngamma\ndelta\n", encoding="utf-8"
    )
    read_result = read_file_execute("edit.py", start_line=2, end_line=3)

    result = edit_lines_execute(
        "edit.py",
        2,
        3,
        "BETA\nGAMMA",
        snapshot_id=read_result.snapshot_id,
        session_id=read_result.session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\nBETA\nGAMMA\ndelta\n"
    )
    assert result.replacement_line_count == 2
    assert "-beta" in result.diff
    assert "+BETA" in result.diff
    assert result.context.numbered_content == (
        "1|alpha\n2|BETA\n3|GAMMA\n4|delta"
    )
    assert result.context.snapshot_id != read_result.snapshot_id


def test_edit_lines_rejects_stale_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\n", encoding="utf-8")
    read_result = read_file_execute("edit.py", start_line=1, end_line=1)
    (tmp_path / "edit.py").write_text("changed\nbeta\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file changed since snapshot"):
        edit_lines_execute(
            "edit.py",
            1,
            1,
            "ALPHA",
            snapshot_id=read_result.snapshot_id,
            session_id=read_result.session_id,
        )


def test_edit_lines_rejects_unseen_snapshot_range(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    read_result = read_file_execute("edit.py", start_line=1, end_line=1)

    with pytest.raises(ValueError, match="edit range was not shown"):
        edit_lines_execute(
            "edit.py",
            2,
            2,
            "BETA",
            snapshot_id=read_result.snapshot_id,
            session_id=read_result.session_id,
        )
