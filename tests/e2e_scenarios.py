import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx
import pytest

from tests.e2e_helpers import ToolClient, assert_required_tools

CORE_TOOL_NAMES = {
    "bash",
    "job",
    "session_start",
    "session_change_cwd",
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
    payload = await client.call_tool("session_start", {"workdir": "."})

    assert payload["target"] == "local"
    assert payload["workdir"] == str(workspace)
    assert payload["workspace_root"] == str(workspace)
    assert len(payload["session_id"]) == 8


async def exercise_explicit_session_workflow(
    client: ToolClient, workspace: Path
) -> None:
    session_dir = workspace / "session-work"
    session_dir.mkdir()
    (session_dir / "notes.txt").write_text(
        "alpha\nneedle one\ngamma\n", encoding="utf-8"
    )

    session = await client.call_tool(
        "session_start", {"workdir": "session-work", "label": "e2e"}
    )
    session_id = session["session_id"]
    assert len(session_id) == 8
    assert session["target"] == "local"
    assert session["workdir"] == str(session_dir)

    read_result = await client.call_tool(
        "read", {"session_id": session_id, "path": "notes.txt:1-2"}
    )
    assert read_result["kind"] == "file"
    assert read_result["content"] == "1|alpha\n2|needle one"
    assert read_result["file"]["session_id"] == session_id
    assert read_result["file"]["snapshot_id"]

    search_result = await client.call_tool(
        "search",
        {
            "session_id": session_id,
            "pattern": "needle",
            "regex": False,
        },
    )
    if search_result["ok"]:
        assert search_result["count"] == 1, search_result
        assert search_result["matches"][0]["session_id"] == session_id
        assert search_result["matches"][0]["numbered_line"] == "2|needle one"
    else:
        assert "rg" in search_result["stderr"]
        assert search_result["matches"] == []

    edit_result = await client.call_tool(
        "edit_lines",
        {
            "session_id": session_id,
            "path": "notes.txt",
            "start_line": 2,
            "end_line": 2,
            "replacement": "needle two\n",
            "snapshot_id": read_result["file"]["snapshot_id"],
        },
    )
    assert "+needle two" in edit_result["diff"]
    assert (session_dir / "notes.txt").read_text(encoding="utf-8") == (
        "alpha\nneedle two\ngamma\n"
    )

    other_dir = workspace / "other-work"
    other_dir.mkdir()
    changed = await client.call_tool(
        "session_change_cwd",
        {"session_id": session_id, "workdir": "other-work"},
    )
    assert changed["session_id"] == session_id
    assert changed["workdir"] == str(other_dir)
    with pytest.raises((AssertionError, httpx.HTTPStatusError)):
        await client.call_tool(
            "read", {"session_id": session_id, "path": "notes.txt"}
        )

    second = await client.call_tool(
        "session_start", {"workdir": "session-work"}
    )
    with pytest.raises((AssertionError, httpx.HTTPStatusError)):
        await client.call_tool(
            "edit_lines",
            {
                "session_id": second["session_id"],
                "path": "notes.txt",
                "start_line": 1,
                "end_line": 1,
                "replacement": "ALPHA\n",
                "snapshot_id": read_result["file"]["snapshot_id"],
            },
        )
    with pytest.raises((AssertionError, httpx.HTTPStatusError)):
        await client.call_tool(
            "read", {"session_id": "BAD00000", "path": "notes.txt"}
        )


async def exercise_filesystem_and_search_tools(
    client: ToolClient, workspace: Path
) -> None:
    session = await client.call_tool("session_start", {"workdir": "."})
    session_id = session["session_id"]

    await client.call_tool(
        "write_file",
        {
            "session_id": session_id,
            "path": "notes/demo.txt",
            "content": "alpha beta\nneedle one\n",
        },
    )
    assert (workspace / "notes" / "demo.txt").read_text(encoding="utf-8") == (
        "alpha beta\nneedle one\n"
    )

    listing = await client.call_tool(
        "list_files", {"session_id": session_id, "path": "notes"}
    )
    assert any(
        row.get("path") == "notes/demo.txt" for row in listing["entries"]
    )

    tree_view_execute = await client.call_tool(
        "tree_view", {"session_id": session_id, "cwd": ".", "depth": 2}
    )
    assert tree_view_execute["exists"] is True
    assert any("notes/" in entry for entry in tree_view_execute["entries"])

    glob_result = await client.call_tool(
        "glob_search",
        {"session_id": session_id, "pattern": "**/*.txt", "cwd": "."},
    )
    assert "notes/demo.txt" in glob_result["paths"]

    search_result = await client.call_tool(
        "search",
        {
            "session_id": session_id,
            "pattern": "needle",
            "paths": "notes/demo.txt",
            "regex": False,
        },
    )
    assert "matches" in search_result
    assert "count" in search_result

    read_result = await client.call_tool(
        "read", {"session_id": session_id, "path": "notes/demo.txt"}
    )
    assert "alpha beta" in read_result["content"]
    assert "needle one" in read_result["content"]

    await client.call_tool(
        "edit_lines",
        {
            "path": "notes/demo.txt",
            "session_id": session_id,
            "start_line": 2,
            "end_line": 2,
            "replacement": "needle two\n",
            "snapshot_id": read_result["file"]["snapshot_id"],
        },
    )
    read_result = await client.call_tool(
        "read", {"session_id": session_id, "path": "notes/demo.txt"}
    )
    await client.call_tool(
        "edit_lines",
        {
            "path": "notes/demo.txt",
            "session_id": session_id,
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
        "apply_patch", {"session_id": session_id, "patch": patch, "cwd": "."}
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
        "secret_scan",
        {"session_id": session_id, "cwd": "notes", "glob": "*.txt"},
    )
    assert scan_result["findings"]
    assert scan_result["findings"][0]["path"] == "notes/token.txt"

    await client.call_tool(
        "delete_file_or_dir",
        {"session_id": session_id, "path": "notes/token.txt"},
    )
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
    session = await client.call_tool("session_start", {"workdir": "."})
    session_id = session["session_id"]

    await assert_required_tools(
        client,
        {"create_file_link", "list_file_links", "revoke_file_link"},
    )
    link = await client.call_tool(
        "create_file_link",
        {
            "session_id": session_id,
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

    listed = await client.call_tool(
        "list_file_links", {"session_id": session_id}
    )
    assert listed == {"links": []}

    second = await client.call_tool(
        "create_file_link",
        {"session_id": session_id, "path": "artifact.bin", "ttl_s": 60},
    )
    revoked = await client.call_tool(
        "revoke_file_link",
        {"session_id": session_id, "token": second["token"]},
    )
    assert revoked == {"revoked": True, "token": second["token"]}

    async with httpx.AsyncClient(timeout=10) as http_client:
        missing = await http_client.get(second["url"])
    assert missing.status_code == 404


async def exercise_shell_tools(client: ToolClient, workspace: Path) -> None:
    shell_dir = workspace / "shell-work"
    shell_dir.mkdir(exist_ok=True)
    (shell_dir / "marker.txt").write_text("e2e-shell", encoding="utf-8")
    session = await client.call_tool(
        "session_start", {"workdir": "shell-work", "label": "shell-e2e"}
    )
    session_id = session["session_id"]

    shell_result = await client.call_tool(
        "bash",
        {
            "session_id": session_id,
            "command": "printf e2e-shell && pwd",
            "timeout_s": 5,
        },
    )
    assert shell_result["mode"] == "command"
    assert shell_result["cwd"] == str(shell_dir)
    assert shell_result["result"]["stdout"].strip() == f"e2e-shell{shell_dir}"

    subdir = shell_dir / "subdir"
    subdir.mkdir()
    subdir_result = await client.call_tool(
        "bash",
        {
            "session_id": session_id,
            "command": "pwd",
            "cwd": "subdir",
            "timeout_s": 5,
        },
    )
    assert subdir_result["cwd"] == str(subdir)
    assert subdir_result["result"]["stdout"].strip() == str(subdir)

    python_result = await client.call_tool(
        "run_python_code",
        {
            "session_id": session_id,
            "code": "import json; print(json.dumps({'e2e': 314}))",
            "timeout_s": 5,
        },
    )
    assert python_result["mode"] == "command"
    assert python_result["result"]["ok"] is True
    assert json.loads(python_result["result"]["stdout"])["e2e"] == 314

    list_persistent_shells = await client.call_tool("list_persistent_shells")
    assert "shells" in list_persistent_shells


async def exercise_session_bound_job_tools(
    client: ToolClient, workspace: Path
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is required for async bash job e2e coverage")

    job_dir = workspace / "job-work"
    other_dir = workspace / "job-other"
    job_dir.mkdir(exist_ok=True)
    other_dir.mkdir(exist_ok=True)
    first = await client.call_tool("session_start", {"workdir": "job-work"})
    second = await client.call_tool("session_start", {"workdir": "job-other"})
    first_session = first["session_id"]
    second_session = second["session_id"]

    started = await client.call_tool(
        "bash",
        {
            "session_id": first_session,
            "command": "python -u -c \"import time; print('job-ready', flush=True); time.sleep(60)\"",
            "async_": True,
            "name": "session-job-e2e",
        },
    )
    job_id = started["result"]["job_id"]
    assert started["mode"] == "job"
    assert started["result"]["session_id"] == first_session
    assert "backend" not in started["result"]
    assert "shell_id" not in started["result"]

    try:
        first_list = await client.call_tool(
            "job", {"session_id": first_session, "list_jobs": True}
        )
        second_list = await client.call_tool(
            "job", {"session_id": second_session, "list_jobs": True}
        )
        assert job_id in {job["job_id"] for job in first_list["jobs"]}
        assert job_id not in {job["job_id"] for job in second_list["jobs"]}

        with pytest.raises((AssertionError, httpx.HTTPStatusError)):
            await client.call_tool(
                "job", {"session_id": second_session, "poll": [job_id]}
            )

        output = ""
        for _ in range(20):
            poll = await client.call_tool(
                "job",
                {"session_id": first_session, "poll": [job_id], "lines": 20},
            )
            output = poll["outputs"][0].get("output", "")
            if "job-ready" in output:
                break
            await asyncio.sleep(0.25)
        assert "job-ready" in output
    finally:
        await client.call_tool(
            "job", {"session_id": first_session, "cancel": [job_id]}
        )


async def exercise_interactive_shell_tools(client: ToolClient) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is required for interactive shell e2e coverage")

    await assert_required_tools(client, INTERACTIVE_SHELL_TOOL_NAMES)
    session = await client.call_tool("session_start", {"workdir": "."})
    started = await client.call_tool(
        "bash",
        {
            "session_id": session["session_id"],
            "command": "bash",
            "pty": True,
            "name": "e2e",
        },
    )
    shell_id = started["result"]["shell_id"]
    try:
        await client.call_tool(
            "send_persistent_shell_input",
            {
                "shell_id": shell_id,
                "input_text": "printf ready",
                "enter": True,
            },
        )
        deadline = time.monotonic() + 5
        output = ""
        while time.monotonic() < deadline:
            read = await client.call_tool(
                "read_persistent_shell_output", {"shell_id": shell_id}
            )
            output = read.get("output", "")
            if "ready" in output:
                break
            time.sleep(0.1)
        assert "ready" in output
    finally:
        await client.call_tool("kill_persistent_shell", {"shell_id": shell_id})


async def exercise_todo_tools(client: ToolClient) -> None:
    session = await client.call_tool("session_start", {"workdir": "."})
    session_id = session["session_id"]
    todos = [
        {
            "id": "e2e-1",
            "content": "verify end-to-end tool routing",
            "status": "in_progress",
            "priority": "high",
        }
    ]
    write_result = await client.call_tool(
        "write_todos", {"session_id": session_id, "todos": todos}
    )
    assert write_result["todos"] == todos

    read_result = await client.call_tool(
        "read_todos", {"session_id": session_id}
    )
    assert read_result["todos"] == todos
