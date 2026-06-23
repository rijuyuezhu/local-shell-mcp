import json
import shutil
import time
from pathlib import Path

import httpx
import pytest

from tests.e2e_helpers import ToolClient, assert_required_tools

CORE_TOOL_NAMES = {
    "bash",
    "environment_info",
    "search",
    "workspace_search",
    "fetch",
    "read",
    "list_files",
    "tree_view",
    "glob_search",
    "write_file",
    "delete_file_or_dir",
    "apply_patch",
    "secret_scan",
    "run_python_code",
    "list_persistent_shells",
    "read_todos",
    "write_todos",
}

INTERACTIVE_SHELL_TOOL_NAMES = {
    "send_persistent_shell_input",
    "read_persistent_shell_output",
    "kill_persistent_shell",
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
    assert any(
        row.get("path") == "notes/demo.txt" for row in listing["entries"]
    )

    tree_view_execute = await client.call_tool(
        "tree_view", {"cwd": ".", "depth": 2}
    )
    assert tree_view_execute["exists"] is True
    assert any("notes/" in entry for entry in tree_view_execute["entries"])

    glob_result = await client.call_tool(
        "glob_search", {"pattern": "**/*.txt", "cwd": "."}
    )
    assert "notes/demo.txt" in glob_result["paths"]

    search_result = await client.call_tool(
        "search",
        {"pattern": "needle", "paths": "notes", "regex": False},
    )
    assert search_result["matches"]
    assert search_result["matches"][0]["path"] == "notes/demo.txt"

    read_result = await client.call_tool("read", {"path": "notes/demo.txt"})
    assert "alpha beta" in read_result["content"]
    assert "needle one" in read_result["content"]

    await client.call_tool(
        "edit_lines",
        {
            "path": "notes/demo.txt",
            "start_line": 2,
            "end_line": 2,
            "replacement": "needle two\n",
            "snapshot_id": read_result["file"]["snapshot_id"],
        },
    )
    read_result = await client.call_tool("read", {"path": "notes/demo.txt"})
    await client.call_tool(
        "edit_lines",
        {
            "path": "notes/demo.txt",
            "start_line": 1,
            "end_line": 1,
            "replacement": "ALPHA BETA\n",
            "snapshot_id": read_result["file"]["snapshot_id"],
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
    search = await client.call_tool(
        "workspace_search", {"query": "patched line"}
    )
    assert "results" in search
    if search["results"]:
        assert search["results"][0]["id"] == "notes/demo.txt"

    fetched = await client.call_tool("fetch", {"id": "notes/demo.txt"})
    assert fetched["id"] == "notes/demo.txt"
    assert "patched line" in fetched["text"]


async def exercise_file_download_links(
    client: ToolClient, base_url: str, workspace: Path
) -> None:
    payload = b"download-payload-\x00-binary"
    (workspace / "artifact.bin").write_bytes(payload)

    await assert_required_tools(
        client,
        {"create_file_link", "list_file_links", "revoke_file_link"},
    )
    link = await client.call_tool(
        "create_file_link",
        {
            "path": "artifact.bin",
            "ttl_s": 60,
            "filename": "result.bin",
            "max_downloads": 1,
        },
    )
    assert link["url"].startswith(f"{base_url}/download/")

    async with httpx.AsyncClient(timeout=10) as http_client:
        response = await http_client.get(link["url"])
        assert response.status_code == 200
        assert response.content == payload
        assert "result.bin" in response.headers["content-disposition"]

        exhausted = await http_client.get(link["url"])
        assert exhausted.status_code == 410

    listed = await client.call_tool("list_file_links")
    assert listed == {"links": []}

    second = await client.call_tool(
        "create_file_link", {"path": "artifact.bin", "ttl_s": 60}
    )
    revoked = await client.call_tool(
        "revoke_file_link", {"token": second["token"]}
    )
    assert revoked == {"revoked": True, "token": second["token"]}

    async with httpx.AsyncClient(timeout=10) as http_client:
        missing = await http_client.get(second["url"])
    assert missing.status_code == 404


async def exercise_shell_tools(client: ToolClient) -> None:
    shell_result = await client.call_tool(
        "bash", {"command": "printf e2e-shell", "timeout_s": 5}
    )
    assert shell_result["mode"] == "command"
    assert shell_result["result"]["stdout"] == "e2e-shell"

    python_result = await client.call_tool(
        "run_python_code",
        {
            "code": "import json; print(json.dumps({'e2e': 314}))",
            "timeout_s": 5,
        },
    )
    assert python_result["ok"] is True
    assert json.loads(python_result["stdout"])["e2e"] == 314

    list_persistent_shells = await client.call_tool("list_persistent_shells")
    assert "sessions" in list_persistent_shells


async def exercise_interactive_shell_tools(client: ToolClient) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is required for interactive shell e2e coverage")

    await assert_required_tools(client, INTERACTIVE_SHELL_TOOL_NAMES)
    started = await client.call_tool(
        "bash", {"command": "bash", "pty": True, "name": "e2e"}
    )
    session_id = started["result"]["session_id"]
    try:
        await client.call_tool(
            "send_persistent_shell_input",
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
                "read_persistent_shell_output", {"session_id": session_id}
            )
            output = read.get("output", "")
            if "ready" in output:
                break
            time.sleep(0.1)
        assert "ready" in output
    finally:
        await client.call_tool(
            "kill_persistent_shell", {"session_id": session_id}
        )


async def exercise_todo_tools(client: ToolClient) -> None:
    todos = [
        {
            "id": "e2e-1",
            "content": "verify end-to-end tool routing",
            "status": "in_progress",
            "priority": "high",
        }
    ]
    write_result = await client.call_tool("write_todos", {"todos": todos})
    assert write_result["todos"] == todos

    read_result = await client.call_tool("read_todos")
    assert read_result["todos"] == todos
