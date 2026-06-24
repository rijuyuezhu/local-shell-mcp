import json
from pathlib import Path

import pytest

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.files import (
    edit_file_execute,
    edit_lines_execute,
    hashline_edit_execute,
    list_files_execute,
    multi_edit_file_execute,
    parse_hashline_edit_input,
    read_file_execute,
    read_many_files_execute,
    write_file_execute,
)
from local_shell_mcp.ops.shell import check_command_policy
from local_shell_mcp.ops.utils.path import resolve_path
from local_shell_mcp.schemas.input_models.files import ReadFileRequest
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tool_session.store import get_tool_session_store
from tests.helpers import nested_mcp_text


def _create_session() -> str:
    store = get_tool_session_store()
    store.clear()
    return store.create_session(workdir=".").session_id


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

    session_id = _create_session()

    result = read_file_execute(
        "lines.txt", start_line=2, end_line=3, session_id=session_id
    )

    assert result.content == "beta\ngamma"
    assert result.start_line == 2
    assert result.end_line == 3
    assert result.line_count == 2
    assert result.lines[0].line == 2
    assert result.lines[0].text == "beta"
    assert result.numbered_content.startswith("[lines.txt#")
    assert result.numbered_content.endswith("]\n2:beta\n3:gamma")
    assert result.session_id == session_id
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
    assert result.numbered_content == "1:hello"


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
    assert ranged.line_ranges == ((50, 69),)
    assert ranged.raw is True
    raw_first = parse_read_target("src/foo.py:raw:10-12")
    assert raw_first.start_line == 10
    assert raw_first.end_line == 12
    assert raw_first.line_ranges == ((10, 12),)
    assert raw_first.raw is True
    multi = parse_read_target("src/foo.py:5-6,10+2:raw")
    assert multi.path == "src/foo.py"
    assert multi.start_line == 5
    assert multi.end_line == 11
    assert multi.line_ranges == ((5, 6), (10, 11))
    assert multi.raw is True


@pytest.mark.parametrize(
    "target",
    [
        "src/foo.py:10-5",
        "src/foo.py:5-8,7-9",
        "src/foo.py:5,10",
        "src/foo.py:5,,10",
    ],
)
def test_parse_read_target_rejects_invalid_multi_range_selectors(target):
    from local_shell_mcp.tool_session.selectors import parse_read_target

    with pytest.raises(ValueError):
        parse_read_target(target)


def test_read_file_execute_multi_ranges_records_grounding_and_edits(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "multi.py").write_text(
        "one\ntwo\nthree\nfour\nfive\n", encoding="utf-8"
    )
    session_id = _create_session()

    read_result = read_file_execute(
        "multi.py",
        session_id=session_id,
        line_ranges=((2, 3), (5, 5)),
    )

    assert [line.line for line in read_result.lines] == [2, 3, 5]
    assert read_result.start_line == 2
    assert read_result.end_line == 5
    assert read_result.line_count == 3
    assert [line.model_dump() for line in read_result.seen_ranges] == [
        {"start": 2, "end": 3},
        {"start": 5, "end": 5},
    ]
    assert read_result.numbered_content.startswith("[multi.py#")
    assert "2:two" in read_result.numbered_content
    assert "3:three" in read_result.numbered_content
    assert "5:five" in read_result.numbered_content
    assert "4:four" not in read_result.numbered_content
    assert read_result.snapshot_id is not None

    with pytest.raises(ValueError, match="not shown"):
        edit_lines_execute(
            "multi.py", 4, 4, "FOUR", read_result.snapshot_id, session_id
        )

    edit_lines_execute(
        "multi.py", 5, 5, "FIVE", read_result.snapshot_id, session_id
    )
    assert (tmp_path / "multi.py").read_text(encoding="utf-8") == (
        "one\ntwo\nthree\nfour\nFIVE\n"
    )


def test_edit_lines_uses_snapshot_and_returns_diff_context(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text(
        "alpha\nbeta\ngamma\ndelta\n", encoding="utf-8"
    )
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=3, session_id=session_id
    )

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
    assert result.context.numbered_content.startswith("[edit.py#")
    assert result.context.numbered_content.endswith(
        "]\n1:alpha\n2:BETA\n3:GAMMA\n4:delta"
    )
    assert result.context.snapshot_id != read_result.snapshot_id


def test_edit_lines_rejects_stale_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=1, end_line=1, session_id=session_id
    )
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
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=1, end_line=1, session_id=session_id
    )

    with pytest.raises(ValueError, match="edit range was not shown"):
        edit_lines_execute(
            "edit.py",
            2,
            2,
            "BETA",
            snapshot_id=read_result.snapshot_id,
            session_id=read_result.session_id,
        )


def test_hashline_edit_replaces_copied_line_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=2, session_id=session_id
    )

    result = hashline_edit_execute(
        f"[edit.py#{read_result.snapshot_id}]\n2:beta\n+BETA",
        session_id=session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\nBETA\ngamma\n"
    )
    assert result.start_line == 2
    assert result.end_line == 2
    assert result.context.numbered_content.startswith("[edit.py#")
    assert result.context.snapshot_id != read_result.snapshot_id


def test_hashline_edit_deletes_when_no_replacement_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=2, session_id=session_id
    )

    hashline_edit_execute(
        f"[edit.py#{read_result.snapshot_id}]\n2:beta",
        session_id=session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\ngamma\n"
    )


def test_hashline_edit_supports_swap_directive(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=3, session_id=session_id
    )

    hashline_edit_execute(
        f"[edit.py#{read_result.snapshot_id}]\nSWAP 2-3:\n+BETA\n+GAMMA",
        session_id=session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\nBETA\nGAMMA\n"
    )


def test_hashline_edit_supports_insert_directive(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=2, session_id=session_id
    )

    hashline_edit_execute(
        f"[edit.py#{read_result.snapshot_id}]\nINSERT BEFORE 2:\n+inserted",
        session_id=session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\ninserted\nbeta\n"
    )


def test_hashline_edit_accepts_workspace_relative_header_from_nested_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    project = tmp_path / "project"
    project.mkdir()
    (project / "edit.py").write_text("alpha\nbeta\n", encoding="utf-8")
    store = get_tool_session_store()
    store.clear()
    session_id = store.create_session(workdir="project").session_id
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=2, session_id=session_id
    )

    assert read_result.path == "project/edit.py"
    payload = (
        "[project/edit.py#"
        + str(read_result.snapshot_id)
        + "]"
        + chr(10)
        + "2:beta"
        + chr(10)
        + "+BETA"
    )
    hashline_edit_execute(payload, session_id=session_id)

    assert (project / "edit.py").read_text(encoding="utf-8") == (
        "alpha\nBETA\n"
    )


def test_hashline_edit_rejects_mismatched_old_text(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=2, end_line=2, session_id=session_id
    )

    with pytest.raises(ValueError, match="old text does not match"):
        hashline_edit_execute(
            f"[edit.py#{read_result.snapshot_id}]\n2:not beta\n+BETA",
            session_id=session_id,
        )


def test_parse_hashline_edit_rejects_non_consecutive_rows():
    with pytest.raises(ValueError, match="consecutive"):
        parse_hashline_edit_input("[a.txt#snap]\n2:b\n4:d\n+x")


def test_hashline_edit_supports_multiple_hunks_same_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text(
        "alpha\nbeta\ngamma\ndelta\n", encoding="utf-8"
    )
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=1, end_line=4, session_id=session_id
    )

    result = hashline_edit_execute(
        f"[edit.py#{read_result.snapshot_id}]\n"
        "2:beta\n"
        "+BETA\n"
        "\n"
        "4:delta\n"
        "+DELTA",
        session_id=session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\nBETA\ngamma\nDELTA\n"
    )
    assert result.hunk_count == 2
    assert [(h.start_line, h.end_line) for h in result.hunks] == [
        (2, 2),
        (4, 4),
    ]
    assert all(h.context.snapshot_id for h in result.hunks)


def test_hashline_edit_supports_multiple_hunks_with_insert(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=1, end_line=3, session_id=session_id
    )

    result = hashline_edit_execute(
        f"[edit.py#{read_result.snapshot_id}]\n"
        "INSERT AFTER 1:\n"
        "+inserted\n"
        "\n"
        "3:gamma\n"
        "+GAMMA",
        session_id=session_id,
    )

    assert (tmp_path / "edit.py").read_text(encoding="utf-8") == (
        "alpha\ninserted\nbeta\nGAMMA\n"
    )
    assert result.hunk_count == 2
    assert result.hunks[0].replacement_line_count == 2
    assert result.hunks[1].replacement_line_count == 1


def test_hashline_edit_supports_multiple_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "one.py").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("gamma\ndelta\n", encoding="utf-8")
    session_id = _create_session()
    one = read_file_execute(
        "one.py", start_line=2, end_line=2, session_id=session_id
    )
    two = read_file_execute(
        "two.py", start_line=1, end_line=1, session_id=session_id
    )

    result = hashline_edit_execute(
        f"[one.py#{one.snapshot_id}]\n"
        "2:beta\n"
        "+BETA\n"
        f"[two.py#{two.snapshot_id}]\n"
        "1:gamma\n"
        "+GAMMA",
        session_id=session_id,
    )

    assert (tmp_path / "one.py").read_text(encoding="utf-8") == "alpha\nBETA\n"
    assert (tmp_path / "two.py").read_text(encoding="utf-8") == "GAMMA\ndelta\n"
    assert result.hunk_count == 2
    assert [h.path for h in result.hunks] == ["one.py", "two.py"]


def test_hashline_edit_rejects_overlapping_hunks(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "edit.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    session_id = _create_session()
    read_result = read_file_execute(
        "edit.py", start_line=1, end_line=3, session_id=session_id
    )

    with pytest.raises(ValueError, match="overlap"):
        hashline_edit_execute(
            f"[edit.py#{read_result.snapshot_id}]\n"
            "1:alpha\n"
            "2:beta\n"
            "+ALPHA\n"
            "+BETA\n"
            "\n"
            "2:beta\n"
            "3:gamma\n"
            "+BETA\n"
            "+GAMMA",
            session_id=session_id,
        )
