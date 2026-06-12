from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tarfile
from collections.abc import AsyncIterator
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
    "remote_invite",
    "remote_list_machines",
    "remote_revoke_machine",
    "remote_rename_machine",
    "remote_environment_info",
    "remote_run_shell_tool",
    "remote_run_python_tool",
    "remote_list_files",
    "remote_read_file",
    "remote_write_file",
    "remote_delete_file_or_dir",
}


@asynccontextmanager
async def run_remote_enabled_mcp_process(
    tmp_path: Path,
) -> AsyncIterator[tuple[str, Path, Path]]:
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
            "LOCAL_SHELL_MCP_STATE_DIR": str(
                remote_workspace / ".local-shell-mcp"
            ),
            "LOCAL_SHELL_MCP_AUDIT_LOG_PATH": str(
                remote_workspace / ".local-shell-mcp" / "audit.jsonl"
            ),
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED": "false",
            "LOCAL_SHELL_MCP_PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S": "5",
            "LOCAL_SHELL_MCP_PUBLIC_RUN_SHELL_MAX_TIMEOUT_S": "10",
            "LOCAL_SHELL_MCP_PUBLIC_TOOL_TIMEOUT_S": "15",
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
        inventory = await client.call_tool("remote_list_machines")
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
        invite = await client.call_tool(
            "remote_invite",
            {"name": machine, "workdir": str(remote_workspace), "ttl_s": 120},
        )
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

        async with httpx.AsyncClient(timeout=20) as http_client:
            bundle_response = await http_client.get(
                f"{base_url}/remote/worker-bundle.tgz"
            )
        bundle_response.raise_for_status()
        bundle_path = tmp_path / "worker-bundle.tgz"
        bundle_path.write_bytes(bundle_response.content)
        with tarfile.open(bundle_path) as bundle:
            assert "local_shell_mcp/remote/join_worker.sh" in bundle.getnames()

        worker = start_worker_process(
            base_url, invite["code"], machine, remote_workspace
        )
        try:
            row = await wait_for_machine(client, worker, machine)
            assert row["workdir"] == str(remote_workspace)

            remote_env = await client.call_tool(
                "remote_environment_info", {"machine": machine}
            )
            assert remote_env["settings"]["workspace_root"] == str(
                remote_workspace
            )
            assert remote_env["settings"]["auth_mode"] == "none"
            assert remote_env["probe"]["ok"] is True
            assert str(remote_workspace) in remote_env["probe"]["stdout"]

            write_result = await client.call_tool(
                "remote_write_file",
                {
                    "machine": machine,
                    "path": "remote/demo.txt",
                    "content": "hello from remote worker\n",
                },
            )
            assert write_result["path"] == "remote/demo.txt"
            assert (
                remote_workspace / "remote" / "demo.txt"
            ).read_text() == "hello from remote worker\n"
            assert not (control_workspace / "remote" / "demo.txt").exists()

            listing = await client.call_tool(
                "remote_list_files", {"machine": machine, "path": "remote"}
            )
            assert any(
                item.get("path") == "remote/demo.txt" for item in listing
            )

            read_result = await client.call_tool(
                "remote_read_file",
                {"machine": machine, "path": "remote/demo.txt"},
            )
            assert read_result["content"] == "hello from remote worker\n"

            shell_result = await client.call_tool(
                "remote_run_shell_tool",
                {
                    "machine": machine,
                    "command": "printf remote-shell-ok",
                    "timeout_s": 5,
                },
            )
            assert shell_result["ok"] is True
            assert shell_result["stdout"] == "remote-shell-ok"

            python_result = await client.call_tool(
                "remote_run_python_tool",
                {
                    "machine": machine,
                    "code": "from pathlib import Path; print(Path.cwd().name)",
                    "timeout_s": 5,
                },
            )
            assert python_result["ok"] is True
            assert python_result["stdout"].strip() == remote_workspace.name

            await client.call_tool(
                "remote_delete_file_or_dir",
                {"machine": machine, "path": "remote/demo.txt"},
            )
            assert not (remote_workspace / "remote" / "demo.txt").exists()

            revoked = await client.call_tool(
                "remote_revoke_machine", {"machine": machine}
            )
            assert revoked == {"machine": machine, "revoked": True}
        finally:
            terminate_process(worker)
