import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import tarfile
import venv
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.types import ImageContent

from tests.e2e_helpers import (
    PROJECT_ROOT,
    ToolClient,
    assert_required_tools,
    free_tcp_port,
    server_env,
    streamable_http_tool_client,
    wait_for_http_ready,
)
from workgate import __version__

pytestmark = pytest.mark.integration

REMOTE_TOOL_NAMES = {
    "remote_admin",
    "session_start",
    "read",
    "search",
    "edit_lines",
    "bash",
    "job",
    "view_image",
    "create_file_link",
    "list_agent_skills",
    "activate_agent_skill",
    "read_agent_skill_file",
}


def start_logged_process(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[Any]:
    """Launch a long-lived child without bounded PIPE buffers."""
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        return subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )


def process_logs(workspace: Path, prefix: str) -> str:
    stdout_path = workspace / f"{prefix}.stdout.log"
    stderr_path = workspace / f"{prefix}.stderr.log"
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    return f"stdout:\n{stdout}\nstderr:\n{stderr}"


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
            "WORKGATE_REMOTE_ENABLED": "true",
            "WORKGATE_REMOTE_POLL_TIMEOUT_S": "1",
            "WORKGATE_REMOTE_JOB_TIMEOUT_S": "15",
        }
    )
    process = start_logged_process(
        [
            sys.executable,
            "-m",
            "workgate.main",
            "server",
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
            "true",
            "--remote-enabled",
            "true",
            "--remote-poll-timeout-s",
            "1",
            "--remote-job-timeout-s",
            "15",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout_path=control_workspace / "server.stdout.log",
        stderr_path=control_workspace / "server.stderr.log",
    )
    try:
        await wait_for_http_ready(base_url, process)
        yield base_url, control_workspace, remote_workspace
    finally:
        terminate_process(process)


def worker_env(remote_workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "WORKGATE_WORKSPACE_ROOT": str(remote_workspace),
            "WORKGATE_STATE_DIR": str(remote_workspace / ".workgate"),
            "WORKGATE_WORKER_STATE_DIR": str(
                remote_workspace / ".workgate-worker"
            ),
            "WORKGATE_AUTH_MODE": "none",
            "WORKGATE_AGENT_BRIDGE_ENABLED": "true",
            "WORKGATE_RUN_SHELL_DEFAULT_TIMEOUT_S": "5",
            "WORKGATE_RUN_SHELL_MAX_TIMEOUT_S": "10",
            "WORKGATE_TOOL_TIMEOUT_S": "15",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def start_worker_process(
    base_url: str,
    invite: str,
    machine: str,
    remote_workspace: Path,
    bundle_path: Path,
) -> subprocess.Popen[Any]:
    state_dir = remote_workspace / ".workgate-worker"
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    runtime_dir = state_dir / "runtimes" / digest
    runtime_dir.mkdir(parents=True)
    with tarfile.open(bundle_path) as bundle:
        bundle.extractall(runtime_dir, filter="data")
    (runtime_dir / "runtime.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_version": __version__,
                "sha256": digest,
                "size": bundle_path.stat().st_size,
                "installed_at": 0,
            }
        ),
        encoding="utf-8",
    )
    dependency_paths = sorted(
        {sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]}
    )

    isolated_venv = state_dir / "e2e-venv"
    venv.EnvBuilder(with_pip=False, clear=True).create(isolated_venv)
    worker_python = (
        isolated_venv / "Scripts" / "python.exe"
        if os.name == "nt"
        else isolated_venv / "bin" / "python"
    )
    isolated_site_probe = subprocess.run(
        [
            str(worker_python),
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        cwd=remote_workspace,
        env=worker_env(remote_workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    assert isolated_site_probe.returncode == 0, isolated_site_probe.stderr
    isolated_site = Path(isolated_site_probe.stdout.strip())
    (isolated_site / "workgate-e2e-deps.pth").write_text(
        "\n".join(
            [
                *dependency_paths,
                (
                    "import os; (os.getenv('COVERAGE_PROCESS_START') or "
                    "os.getenv('COVERAGE_PROCESS_CONFIG')) and "
                    "__import__('coverage').process_startup(slug='pth')"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    isolation_probe = subprocess.run(
        [
            str(worker_python),
            "-c",
            (
                "import importlib.util; "
                "print(importlib.util.find_spec('workgate')); "
                "print(bool(importlib.util.find_spec('coverage')))"
            ),
        ],
        cwd=remote_workspace,
        env=worker_env(remote_workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    assert isolation_probe.returncode == 0, isolation_probe.stderr
    assert isolation_probe.stdout.splitlines() == ["None", "True"]

    env = worker_env(remote_workspace)
    env["PYTHONPATH"] = str(runtime_dir)
    env["WORKGATE_WORKER_RUNTIME_SHA256"] = digest
    return start_logged_process(
        [
            str(worker_python),
            "-m",
            "workgate.remote_worker",
            "connect",
            "--server",
            base_url,
            "--invite",
            invite,
            "--name",
            machine,
            "--workdir",
            str(remote_workspace),
            "--profile",
            "p_e2e00000",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout_path=remote_workspace / "worker.stdout.log",
        stderr_path=remote_workspace / "worker.stderr.log",
    )


def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def wait_for_machine(
    client: ToolClient,
    process: subprocess.Popen[Any],
    machine: str,
    remote_workspace: Path,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        if process.poll() is not None:
            raise AssertionError(
                f"worker exited early with code {process.returncode}\n"
                f"{process_logs(remote_workspace, 'worker')}"
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
        assert "remote" not in await client.list_tools()

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

        async with httpx.AsyncClient(
            timeout=10, trust_env=False
        ) as http_client:
            join_response = await http_client.get(invite["join_url"])
        join_response.raise_for_status()
        join_script = join_response.text
        assert "__REMOTE_SERVER__" not in join_script
        assert "__REMOTE_WORKER_BUNDLE_PATH__" not in join_script
        assert f"SERVER={base_url}" in join_script
        assert 'BUNDLE_URL="$SERVER/remote/worker-bundle.tgz"' in join_script
        assert 'RUNTIME_DIR="$DATA_DIR/runtimes/$RUNTIME_DIGEST"' in join_script
        assert "runtime_is_installed" in join_script
        assert "Reusing worker runtime" in join_script
        assert (
            'export WORKGATE_WORKER_RUNTIME_SHA256="$RUNTIME_DIGEST"'
            in join_script
        )
        assert (
            'export PYTHONPATH="$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}"'
            in join_script
        )
        assert "python_supports_worker" in join_script
        assert "python install 3.14" in join_script
        assert "Downloading worker manifest" in join_script
        assert "Downloading worker bundle" in join_script
        assert "Cache-Control: no-cache" in join_script
        assert "Preparing shared worker runtime" in join_script
        assert "os.replace(staging, runtime)" in join_script
        assert "member.isreg()" in join_script
        assert "curl -fSs" in join_script
        assert "-m workgate.remote_worker" in join_script
        assert "python3 -m workgate.main worker" not in join_script

        async with httpx.AsyncClient(
            timeout=20, trust_env=False
        ) as http_client:
            bundle_response = await http_client.get(
                f"{base_url}/remote/worker-bundle.tgz"
            )
        bundle_response.raise_for_status()
        bundle_path = tmp_path / "worker-bundle.tgz"
        bundle_path.write_bytes(bundle_response.content)
        with tarfile.open(bundle_path) as bundle:
            names = bundle.getnames()
            assert "workgate/remote_worker/__main__.py" in names
            assert "workgate/remote_worker/worker.py" in names
            assert "workgate/remote_worker/compat.py" in names
            assert "workgate/remote_worker/profiles.py" in names
            assert "workgate/remote_worker/runtime.py" in names
            assert "workgate/remote_worker/cli.py" in names
            assert "workgate/remote_worker/service.py" in names
            assert "workgate/remote/join_worker.sh" not in names
            assert "workgate/remote/manager.py" not in names
            assert "workgate/remote/http.py" not in names
            assert not any(name.startswith("vendor/") for name in names)
            assert not any(
                name.startswith("workgate/ui/static/") or "ui_static" in name
                for name in names
            )
            assert all(name.endswith(".py") for name in names)

        worker = start_worker_process(
            base_url,
            invite["code"],
            machine,
            remote_workspace,
            bundle_path,
        )
        try:
            row = await wait_for_machine(
                client, worker, machine, remote_workspace
            )
            assert row["workdir"] == str(remote_workspace)

            (remote_workspace / "remote").mkdir()
            (remote_workspace / "remote" / "demo.txt").write_text(
                "hello from remote worker\nsecond remote line\n",
                encoding="utf-8",
            )
            assert not (control_workspace / "remote" / "demo.txt").exists()
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lP7LAAAAAElFTkSuQmCC"
            )
            (remote_workspace / "remote" / "pixel.png").write_bytes(png)
            remote_skill = (
                remote_workspace / ".agents" / "skills" / "remote-skill"
            )
            remote_skill.mkdir(parents=True)
            (remote_skill / "SKILL.md").write_text(
                "# Remote Skill\n\nUse the remote workspace.\n",
                encoding="utf-8",
            )
            (remote_skill / "guide.md").write_text(
                "remote guide\n", encoding="utf-8"
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
            environment = first_class_session["environment"]
            assert environment["workspace"]["workspace_root"] == str(
                remote_workspace
            )
            assert environment["workspace"]["workdir"] == str(remote_workspace)
            assert environment["workspace"]["target"] == "remote"
            assert environment["workspace"]["machine"] == machine
            assert environment["workspace"]["worker_runtime"]["active"] is True
            assert (
                environment["workspace"]["worker_runtime"]["service_status"]
                == "running"
            )
            assert environment["runtime"]["python_version"]
            assert set(environment["tools"]) == {
                "shell",
                "git",
                "ripgrep",
                "tmux",
                "curl",
                "bun",
                "chromium",
                "playwright",
                "opentui",
            }
            assert environment["capabilities"]["oauth_mcp_clients"] is False

            orientation_dir = remote_workspace / "orientation"
            orientation_dir.mkdir()
            (orientation_dir / "AGENTS.md").write_text(
                "remote orientation instructions\n", encoding="utf-8"
            )
            changed = await client.call_tool(
                "session_change_cwd",
                {
                    "session_id": first_class_session_id,
                    "workdir": "orientation",
                },
            )
            assert changed["session_id"] == first_class_session_id
            assert changed["workdir"] == str(orientation_dir)
            assert changed["instruction_files"] == ["orientation/AGENTS.md"]
            assert changed["environment"]["workspace"]["workdir"] == str(
                orientation_dir
            )
            assert changed["environment"]["workspace"]["target"] == "remote"
            assert changed["environment"]["workspace"]["machine"] == machine
            restored = await client.call_tool(
                "session_change_cwd",
                {
                    "session_id": first_class_session_id,
                    "workdir": str(remote_workspace),
                },
            )
            assert restored["workdir"] == str(remote_workspace)

            remote_skills = await client.call_tool(
                "list_agent_skills", {"session_id": first_class_session_id}
            )
            assert [row["name"] for row in remote_skills["skills"]] == [
                "remote-skill"
            ]
            assert remote_skills["skills"][0]["source"] == "project"
            remote_activated = await client.call_tool(
                "activate_agent_skill",
                {"name": "remote-skill", "session_id": first_class_session_id},
            )
            assert remote_activated["source"] == "project"
            assert "remote workspace" in remote_activated["content"]
            remote_guide = await client.call_tool(
                "read_agent_skill_file",
                {
                    "name": "remote-skill",
                    "path": "guide.md",
                    "session_id": first_class_session_id,
                },
            )
            assert remote_guide["content"] == "remote guide\n"
            assert remote_guide["source"] == "project"

            image_result = await client.call_tool_result(
                "view_image",
                {
                    "session_id": first_class_session_id,
                    "path": "remote/pixel.png",
                },
            )
            assert image_result.isError is False
            assert isinstance(image_result.content[0], ImageContent)
            assert base64.b64decode(image_result.content[0].data) == png
            assert image_result.structuredContent == {
                "session_id": first_class_session_id,
                "target": "remote",
                "machine": machine,
                "path": "remote/pixel.png",
                "mime_type": "image/png",
                "bytes": len(png),
            }

            remote_download_source = (
                remote_workspace / "remote" / "download-snapshot.txt"
            )
            remote_download_source.write_text(
                "remote creation-time snapshot", encoding="utf-8"
            )
            remote_link = await client.call_tool(
                "create_file_link",
                {
                    "session_id": first_class_session_id,
                    "path": "remote/download-snapshot.txt",
                    "inline": True,
                },
            )
            assert remote_link["target"] == "remote"
            assert remote_link["machine"] == machine
            assert remote_link["inline"] is True
            remote_download_source.write_text(
                "changed after link creation", encoding="utf-8"
            )
            async with httpx.AsyncClient(trust_env=False) as download_client:
                download_response = await download_client.get(
                    remote_link["url"]
                )
            assert download_response.status_code == 200
            assert download_response.text == "remote creation-time snapshot"
            assert (
                download_response.headers["content-security-policy"]
                == "sandbox"
            )
            assert (
                download_response.headers["x-content-type-options"] == "nosniff"
            )

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
            assert "count" in first_class_search
            assert "matches" in first_class_search

            hashline_edit = await client.call_tool(
                "hashline_edit",
                {
                    "session_id": first_class_session_id,
                    "input": (
                        f"[remote/demo.txt#{first_class_snapshot_id}]\n"
                        "1:hello from remote worker\n"
                        "+edited through hashline remote session"
                    ),
                },
            )
            assert (
                hashline_edit["context"]["session_id"] == first_class_session_id
            )
            assert (remote_workspace / "remote" / "demo.txt").read_text() == (
                "edited through hashline remote session\nsecond remote line\n"
            )
            assert not (control_workspace / "remote" / "demo.txt").exists()

            second_line_read = await client.call_tool(
                "read",
                {
                    "session_id": first_class_session_id,
                    "path": "remote/demo.txt:2",
                },
            )
            second_line_snapshot_id = second_line_read["file"]["snapshot_id"]

            first_class_edit = await client.call_tool(
                "edit_lines",
                {
                    "session_id": first_class_session_id,
                    "path": "remote/demo.txt",
                    "start_line": 2,
                    "end_line": 2,
                    "replacement": "edited through structured remote edit",
                    "snapshot_id": second_line_snapshot_id,
                },
            )
            assert (
                first_class_edit["context"]["session_id"]
                == first_class_session_id
            )
            assert (remote_workspace / "remote" / "demo.txt").read_text() == (
                "edited through hashline remote session\n"
                "edited through structured remote edit\n"
            )
            assert not (control_workspace / "remote" / "demo.txt").exists()

            patch_result = await client.call_tool(
                "apply_patch",
                {
                    "session_id": first_class_session_id,
                    "cwd": ".",
                    "patch": """*** Begin Patch
*** Update File: remote/demo.txt
@@
-edited through structured remote edit
+edited through remote apply_patch
*** End Patch
""",
                },
            )
            assert patch_result["checked"] is True
            assert patch_result["applied"] is True
            assert (remote_workspace / "remote" / "demo.txt").read_text() == (
                "edited through hashline remote session\n"
                "edited through remote apply_patch\n"
            )
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

            tmux_check = await client.call_tool(
                "bash",
                {
                    "session_id": first_class_session_id,
                    "command": "command -v tmux",
                    "timeout_s": 5,
                },
            )
            if tmux_check["result"]["ok"]:
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
                first_class_poll = None
                for _ in range(40):
                    first_class_poll = await client.call_tool(
                        "job",
                        {
                            "session_id": first_class_session_id,
                            "poll": [first_class_job_id],
                            "lines": 20,
                        },
                    )
                    first_class_output = first_class_poll["outputs"][0]
                    if first_class_output["job"]["status"] in {
                        "succeeded",
                        "failed",
                        "lost",
                    }:
                        break
                    await asyncio.sleep(0.25)
                assert first_class_poll is not None
                first_class_output = first_class_poll["outputs"][0]
                assert first_class_output["job"]["status"] == "succeeded"
                assert first_class_output["job"]["exit_code"] == 0
                assert "first-class-job" in first_class_output["output"]

            delete_result = await client.call_tool(
                "bash",
                {
                    "session_id": first_class_session_id,
                    "command": "rm remote/demo.txt",
                    "timeout_s": 5,
                },
            )
            assert delete_result["result"]["ok"] is True
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
