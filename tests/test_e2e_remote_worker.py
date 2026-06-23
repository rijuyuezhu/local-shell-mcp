import asyncio
import os
import subprocess
import sys
import tarfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.e2e_helpers import (
    PROJECT_ROOT,
    SRC_ROOT,
    ToolClient,
    assert_required_tools,
    free_tcp_port,
    server_env,
    streamable_http_tool_client,
    wait_for_http_ready,
)

pytestmark = pytest.mark.integration

REMOTE_TOOL_NAMES = {
    "remote",
    "remote_admin",
    "session_start",
    "read",
    "search",
    "edit_lines",
    "bash",
    "job",
}


@asynccontextmanager
async def run_remote_enabled_mcp_process(
    tmp_path: Path,
) -> AsyncGenerator[tuple[str, Path, Path]]:
    control_workspace = tmp_path / "workspace-control"
    remote_workspace = tmp_path / "workspace-remote"
    control_workspace.mkdir()
    remote_workspace.mkdir()
    port = free_tcp_port()
    base_url = f"http://127.0.0.1:{port}"
    env = server_env(control_workspace, mode="mcp", port=port)
    env.update(
        {
            "LOCAL_SHELL_MCP_REMOTE_ENABLED": "true",
            "LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S": "1",
            "LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S": "15",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "local_shell_mcp.main",
            "--mode",
            "mcp",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--auth-mode",
            "none",
            "--workspace-root",
            str(control_workspace),
            "--agent-bridge-enabled",
            "false",
            "--remote-enabled",
            "true",
            "--remote-poll-timeout-s",
            "1",
            "--remote-job-timeout-s",
            "15",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        await wait_for_http_ready(base_url, process)
        yield base_url, control_workspace, remote_workspace
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


def worker_env(remote_workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(SRC_ROOT)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(remote_workspace),
            "LOCAL_SHELL_MCP_STATE_DIR": str(
                remote_workspace / ".local-shell-mcp"
            ),
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED": "false",
            "LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S": "5",
            "LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S": "10",
            "LOCAL_SHELL_MCP_TOOL_TIMEOUT_S": "15",
            "LOCAL_SHELL_MCP_MAX_READ_MANY_FILES": "1",
        }
    )
    return env


def start_worker_process(
    base_url: str, invite: str, machine: str, remote_workspace: Path
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "local_shell_mcp.main",
            "worker",
            "--server",
            base_url,
            "--invite",
            invite,
            "--name",
            machine,
            "--workdir",
            str(remote_workspace),
        ],
        cwd=PROJECT_ROOT,
        env=worker_env(remote_workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


async def wait_for_machine(
    client: ToolClient,
    process: subprocess.Popen[str],
    machine: str,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(
                f"worker exited early with code {process.returncode}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        inventory_result = await client.call_tool(
            "remote_admin", {"action": "list", "args": {}}
        )
        inventory = inventory_result["data"]
        for row in inventory.get("machines", []):
            if row.get("name") == machine and row.get("status") == "online":
                return row
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"remote worker {machine!r} did not become online; "
                f"last inventory: {inventory}"
            )
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_mcp_remote_worker_process_exercises_remote_tool_categories(
    tmp_path: Path,
):
    async with (
        run_remote_enabled_mcp_process(tmp_path) as (
            base_url,
            control_workspace,
            remote_workspace,
        ),
        streamable_http_tool_client(base_url) as client,
    ):
        await assert_required_tools(client, REMOTE_TOOL_NAMES)

        machine = "e2e-remote"
        invite_result = await client.call_tool(
            "remote_admin",
            {
                "action": "invite",
                "args": {
                    "name": machine,
                    "workdir": str(remote_workspace),
                    "ttl_s": 120,
                },
            },
        )
        invite = invite_result["data"]
        assert invite["join_url"] == f"{base_url}/join"
        assert "curl -fsSL" in invite["command"]

        async with httpx.AsyncClient(timeout=10) as http_client:
            join_response = await http_client.get(invite["join_url"])
        join_response.raise_for_status()
        join_script = join_response.text
        assert "__REMOTE_SERVER__" not in join_script
        assert "__REMOTE_WORKER_BUNDLE_PATH__" not in join_script
        assert f"SERVER={base_url}" in join_script
        assert 'BUNDLE_URL="$SERVER/remote/worker-bundle.tgz"' in join_script
        assert (
            'export PYTHONPATH="$TMPDIR:$TMPDIR/vendor:${PYTHONPATH:-}"'
            in join_script
        )
        assert "Downloading worker bundle" in join_script
        assert "curl -fL --progress-bar" in join_script
        assert "python3 -m local_shell_mcp.remote_worker" in join_script
        assert "python3 -m local_shell_mcp.main worker" not in join_script

        async with httpx.AsyncClient(timeout=20) as http_client:
            bundle_response = await http_client.get(
                f"{base_url}/remote/worker-bundle.tgz"
            )
        bundle_response.raise_for_status()
        bundle_path = tmp_path / "worker-bundle.tgz"
        bundle_path.write_bytes(bundle_response.content)
        with tarfile.open(bundle_path) as bundle:
            names = bundle.getnames()
            assert "local_shell_mcp/remote/join_worker.sh" in names
            assert "local_shell_mcp/" + "remote" + "_worker.py" in names

        worker = start_worker_process(
            base_url, invite["code"], machine, remote_workspace
        )
        try:
            row = await wait_for_machine(client, worker, machine)
            assert row["workdir"] == str(remote_workspace)

            write_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "write_file",
                    "args": {
                        "path": "remote/demo.txt",
                        "content": "hello from remote worker\n",
                    },
                },
            )
            write_result = write_result["data"]
            assert write_result["path"] == "remote/demo.txt"
            assert (
                remote_workspace / "remote" / "demo.txt"
            ).read_text() == "hello from remote worker\n"
            assert not (control_workspace / "remote" / "demo.txt").exists()

            listing = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "list_files",
                    "args": {"path": "remote"},
                },
            )
            listing = listing["data"]
            assert any(
                item.get("path") == "remote/demo.txt"
                for item in listing["entries"]
            )

            first_class_session = await client.call_tool(
                "session_start",
                {
                    "target": "remote",
                    "machine": machine,
                    "workdir": ".",
                    "label": "remote-e2e",
                },
            )
            first_class_session_id = first_class_session["session_id"]
            assert first_class_session["target"] == "remote"
            assert first_class_session["machine"] == machine
            assert "worker_session_id" not in first_class_session

            first_class_read = await client.call_tool(
                "read",
                {
                    "session_id": first_class_session_id,
                    "path": "remote/demo.txt:1",
                },
            )
            assert first_class_read["kind"] == "file"
            assert "hello from remote worker" in first_class_read["content"]
            assert (
                first_class_read["file"]["session_id"] == first_class_session_id
            )
            first_class_snapshot_id = first_class_read["file"]["snapshot_id"]

            first_class_search = await client.call_tool(
                "search",
                {
                    "session_id": first_class_session_id,
                    "pattern": "hello",
                    "paths": ["remote/demo.txt"],
                    "regex": False,
                },
            )
            assert first_class_search["count"] == 1
            assert (
                first_class_search["matches"][0]["session_id"]
                == first_class_session_id
            )

            first_class_edit = await client.call_tool(
                "edit_lines",
                {
                    "session_id": first_class_session_id,
                    "path": "remote/demo.txt",
                    "start_line": 1,
                    "end_line": 1,
                    "replacement": "edited through first-class remote session",
                    "snapshot_id": first_class_snapshot_id,
                },
            )
            assert (
                first_class_edit["context"]["session_id"]
                == first_class_session_id
            )
            assert (
                remote_workspace / "remote" / "demo.txt"
            ).read_text() == "edited through first-class remote session\n"
            assert not (control_workspace / "remote" / "demo.txt").exists()

            first_class_bash = await client.call_tool(
                "bash",
                {
                    "session_id": first_class_session_id,
                    "command": "printf first-class-remote-shell",
                    "timeout_s": 5,
                },
            )
            assert first_class_bash["mode"] == "command"
            assert (
                first_class_bash["result"]["stdout"]
                == "first-class-remote-shell"
            )

            first_class_job = await client.call_tool(
                "bash",
                {
                    "session_id": first_class_session_id,
                    "command": (
                        "python -c 'import time; "
                        'print("first-class-job", flush=True); '
                        "time.sleep(3)'"
                    ),
                    "async_": True,
                    "name": "first-class-remote-job",
                },
            )
            first_class_job_id = first_class_job["result"]["job_id"]
            assert (
                first_class_job["result"]["session_id"]
                == first_class_session_id
            )
            first_class_jobs = await client.call_tool(
                "job",
                {
                    "session_id": first_class_session_id,
                    "list_jobs": True,
                },
            )
            assert any(
                item["job_id"] == first_class_job_id
                and item["session_id"] == first_class_session_id
                for item in first_class_jobs["jobs"]
            )
            await client.call_tool(
                "job",
                {
                    "session_id": first_class_session_id,
                    "cancel": [first_class_job_id],
                },
            )

            remote_session = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "session_start",
                    "args": {"workdir": "."},
                },
            )
            remote_session_id = remote_session["data"]["session_id"]

            shell_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "bash",
                    "args": {
                        "session_id": remote_session_id,
                        "command": "printf remote-shell-ok",
                        "timeout_s": 5,
                    },
                },
            )
            assert shell_result["data"]["mode"] == "command"
            assert shell_result["data"]["result"]["stdout"] == "remote-shell-ok"

            python_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "python",
                    "args": {
                        "code": "from pathlib import Path; print(Path.cwd().name)",
                        "timeout_s": 5,
                    },
                },
            )
            assert python_result["data"]["ok"] is True
            assert (
                python_result["data"]["stdout"].strip() == remote_workspace.name
            )

            (control_workspace / "local.bin").write_bytes(
                b"local-to-remote-\x00-payload"
            )
            push_file_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "transfer",
                    "args": {
                        "action": "push_file",
                        "local_path": "local.bin",
                        "remote_path": "remote/pushed.bin",
                        "chunk_size": 5,
                    },
                },
            )
            push_file = push_file_result["data"]
            assert push_file["bytes"] == len(b"local-to-remote-\x00-payload")
            assert push_file["chunks"] > 1
            assert (
                remote_workspace / "remote" / "pushed.bin"
            ).read_bytes() == (b"local-to-remote-\x00-payload")

            pull_file_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "transfer",
                    "args": {
                        "action": "pull_file",
                        "remote_path": "remote/pushed.bin",
                        "local_path": "pulled.bin",
                        "chunk_size": 4,
                    },
                },
            )
            pull_file = pull_file_result["data"]
            assert pull_file["chunks"] > 1
            assert (control_workspace / "pulled.bin").read_bytes() == (
                b"local-to-remote-\x00-payload"
            )

            (control_workspace / "tree_view_execute" / "nested").mkdir(
                parents=True
            )
            (
                control_workspace / "tree_view_execute" / "nested" / "file.txt"
            ).write_text("directory payload", encoding="utf-8")
            push_dir_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "transfer",
                    "args": {
                        "action": "push_dir",
                        "local_path": "tree_view_execute",
                        "remote_path": "remote/tree_view_execute-copy",
                        "chunk_size": 128,
                    },
                },
            )
            push_dir = push_dir_result["data"]
            assert push_dir["entries"] >= 1
            assert (
                remote_workspace
                / "remote"
                / "tree_view_execute-copy"
                / "nested"
                / "file.txt"
            ).read_text(encoding="utf-8") == "directory payload"

            pull_dir_result = await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "transfer",
                    "args": {
                        "action": "pull_dir",
                        "remote_path": "remote/tree_view_execute-copy",
                        "local_path": "tree_view_execute-pulled",
                        "chunk_size": 128,
                    },
                },
            )
            pull_dir = pull_dir_result["data"]
            assert pull_dir["entries"] >= 1
            assert (
                control_workspace
                / "tree_view_execute-pulled"
                / "nested"
                / "file.txt"
            ).read_text(encoding="utf-8") == "directory payload"

            await client.call_tool(
                "remote",
                {
                    "machine": machine,
                    "op": "delete",
                    "args": {"path": "remote/demo.txt"},
                },
            )
            assert not (remote_workspace / "remote" / "demo.txt").exists()

            revoked = await client.call_tool(
                "remote_admin",
                {"action": "revoke", "args": {"machine": machine}},
            )
            assert revoked == {
                "action": "revoke",
                "data": {"machine": machine, "revoked": True},
            }
        finally:
            terminate_process(worker)
