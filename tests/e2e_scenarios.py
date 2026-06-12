from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from tests.e2e_helpers import ToolClient, assert_required_tools

CORE_TOOL_NAMES = {
    "environment_info",
    "search",
    "fetch",
    "list_files",
    "tree_view",
    "glob_search",
    "grep_search",
    "read_file",
    "read_many_files",
    "write_file",
    "edit_file",
    "multi_edit_file",
    "delete_file_or_dir",
    "apply_patch",
    "secret_scan",
    "run_shell_tool",
    "run_python_tool",
    "shell_list",
    "todo_read_tool",
    "todo_write_tool",
}

INTERACTIVE_SHELL_TOOL_NAMES = {
    "shell_start",
    "shell_send",
    "shell_read",
    "shell_kill",
}


async def assert_core_tool_surface(client: ToolClient) -> None:
    await assert_required_tools(client, CORE_TOOL_NAMES)


async def exercise_environment_tool(
    client: ToolClient, workspace: Path
) -> None:
    payload = await client.call_tool("environment_info")

    assert payload["settings"]["workspace_root"] == str(workspace)
    assert payload["settings"]["auth_mode"] == "none"
    assert payload["probe"]["ok"] is True
    assert "Python" in payload["probe"]["stdout"]


async def exercise_filesystem_and_search_tools(
    client: ToolClient, workspace: Path
) -> None:
    await client.call_tool(
        "write_file",
        {
            "path": "notes/demo.txt",
            "content": "alpha beta\nneedle one\n",
        },
    )
    assert (workspace / "notes" / "demo.txt").read_text(encoding="utf-8") == (
        "alpha beta\nneedle one\n"
    )

    listing = await client.call_tool("list_files", {"path": "notes"})
    assert any(row.get("path") == "notes/demo.txt" for row in listing)

    tree = await client.call_tool("tree_view", {"cwd": ".", "depth": 2})
    assert tree["exists"] is True
    assert any("notes/" in entry for entry in tree["entries"])

    glob_result = await client.call_tool(
        "glob_search", {"pattern": "**/*.txt", "cwd": "."}
    )
    assert "notes/demo.txt" in glob_result["paths"]

    grep_result = await client.call_tool(
        "grep_search",
        {"query": "needle", "cwd": ".", "glob": "**/*.txt", "regex": False},
    )
    assert grep_result["matches"]
    assert grep_result["matches"][0]["path"] == "notes/demo.txt"

    read_result = await client.call_tool(
        "read_file", {"path": "notes/demo.txt"}
    )
    assert read_result["content"] == "alpha beta\nneedle one\n"

    many_result = await client.call_tool(
        "read_many_files", {"paths": ["notes/demo.txt"]}
    )
    assert many_result["files"][0]["content"] == "alpha beta\nneedle one\n"

    await client.call_tool(
        "edit_file",
        {"path": "notes/demo.txt", "old": "needle one", "new": "needle two"},
    )
    await client.call_tool(
        "multi_edit_file",
        {
            "path": "notes/demo.txt",
            "edits": [
                {"old": "alpha", "new": "ALPHA"},
                {"old": "beta", "new": "BETA"},
            ],
        },
    )
    assert (workspace / "notes" / "demo.txt").read_text(encoding="utf-8") == (
        "ALPHA BETA\nneedle two\n"
    )

    patch = """diff --git a/notes/demo.txt b/notes/demo.txt
--- a/notes/demo.txt
+++ b/notes/demo.txt
@@ -1,2 +1,3 @@
 ALPHA BETA
 needle two
+patched line
"""
    patch_result = await client.call_tool(
        "apply_patch", {"patch": patch, "cwd": "."}
    )
    assert patch_result["ok"] is True
    assert "patched line" in (workspace / "notes" / "demo.txt").read_text(
        encoding="utf-8"
    )

    scan_file = workspace / "notes" / "token.txt"
    scan_file.write_text(
        "password = 'local-only-test-value'\n",
        encoding="utf-8",
    )
    scan_result = await client.call_tool(
        "secret_scan", {"cwd": "notes", "glob": "*.txt"}
    )
    assert scan_result["findings"]
    assert scan_result["findings"][0]["path"] == "notes/token.txt"

    await client.call_tool("delete_file_or_dir", {"path": "notes/token.txt"})
    assert not scan_file.exists()


async def exercise_workspace_connector_tools(client: ToolClient) -> None:
    search = await client.call_tool("search", {"query": "patched line"})
    assert search["results"]
    first_result = search["results"][0]
    assert first_result["id"] == "notes/demo.txt"

    fetched = await client.call_tool("fetch", {"id": first_result["id"]})
    assert fetched["id"] == "notes/demo.txt"
    assert "patched line" in fetched["text"]


async def exercise_shell_tools(client: ToolClient) -> None:
    shell_result = await client.call_tool(
        "run_shell_tool", {"command": "printf e2e-shell", "timeout_s": 5}
    )
    assert shell_result["ok"] is True
    assert shell_result["stdout"] == "e2e-shell"

    python_result = await client.call_tool(
        "run_python_tool",
        {
            "code": "import json; print(json.dumps({'e2e': 314}))",
            "timeout_s": 5,
        },
    )
    assert python_result["ok"] is True
    assert json.loads(python_result["stdout"])["e2e"] == 314

    shell_list = await client.call_tool("shell_list")
    assert "sessions" in shell_list


async def exercise_interactive_shell_tools(client: ToolClient) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is required for interactive shell e2e coverage")

    await assert_required_tools(client, INTERACTIVE_SHELL_TOOL_NAMES)
    started = await client.call_tool("shell_start", {"name": "e2e"})
    session_id = started["session_id"]
    try:
        await client.call_tool(
            "shell_send",
            {
                "session_id": session_id,
                "input_text": "printf ready",
                "enter": True,
            },
        )
        deadline = time.monotonic() + 5
        output = ""
        while time.monotonic() < deadline:
            read = await client.call_tool(
                "shell_read", {"session_id": session_id}
            )
            output = read.get("output", "")
            if "ready" in output:
                break
            time.sleep(0.1)
        assert "ready" in output
    finally:
        await client.call_tool("shell_kill", {"session_id": session_id})


async def exercise_todo_tools(client: ToolClient) -> None:
    todos = [
        {
            "id": "e2e-1",
            "content": "verify end-to-end tool routing",
            "status": "in_progress",
            "priority": "high",
        }
    ]
    write_result = await client.call_tool("todo_write_tool", {"todos": todos})
    assert write_result["todos"] == todos

    read_result = await client.call_tool("todo_read_tool")
    assert read_result["todos"] == todos
