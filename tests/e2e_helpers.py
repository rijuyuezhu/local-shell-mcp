import asyncio
import json
import os
import socket
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


class ToolClient(Protocol):
    async def list_tools(self) -> set[str]: ...

    async def call_tool(
        self, name: str, args: dict[str, Any] | None = None
    ) -> Any: ...


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def server_env(
    workspace_root: Path, *, mode: str, port: int | None = None
) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(SRC_ROOT)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace_root),
            "LOCAL_SHELL_MCP_STATE_DIR": str(
                workspace_root / ".local-shell-mcp"
            ),
            "LOCAL_SHELL_MCP_MODE": mode,
            "LOCAL_SHELL_MCP_HOST": "127.0.0.1",
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED": "false",
            "LOCAL_SHELL_MCP_REMOTE_ENABLED": "false",
            "LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S": "5",
            "LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S": "10",
            "LOCAL_SHELL_MCP_TOOL_TIMEOUT_S": "15",
        }
    )
    if port is not None:
        env["LOCAL_SHELL_MCP_PORT"] = str(port)
        env["LOCAL_SHELL_MCP_BASE_URL"] = f"http://127.0.0.1:{port}"
    return env


async def wait_for_http_ready(
    base_url: str, process: subprocess.Popen[str]
) -> None:
    deadline = asyncio.get_running_loop().time() + 10
    async with httpx.AsyncClient(timeout=1) as client:
        while True:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    f"server exited early with code {process.returncode}\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )
            try:
                response = await client.get(f"{base_url}/healthz")
                if (
                    response.status_code == 200
                    and response.json().get("ok") is True
                ):
                    return
            except httpx.HTTPError, json.JSONDecodeError:
                pass
            if asyncio.get_running_loop().time() >= deadline:
                process.terminate()
                stdout, stderr = process.communicate(timeout=2)
                raise AssertionError(
                    f"server did not become ready at {base_url}\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )
            await asyncio.sleep(0.05)


@asynccontextmanager
async def run_http_process(
    tmp_path: Path, *, mode: str
) -> AsyncGenerator[tuple[str, Path]]:
    workspace = tmp_path / f"workspace-{mode}"
    workspace.mkdir()
    port = free_tcp_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "local_shell_mcp.main",
            "--mode",
            mode,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--auth-mode",
            "none",
            "--workspace-root",
            str(workspace),
            "--agent-bridge-enabled",
            "false",
            "--remote-enabled",
            "false",
        ],
        cwd=PROJECT_ROOT,
        env=server_env(workspace, mode=mode, port=port),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        await wait_for_http_ready(base_url, process)
        yield base_url, workspace
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


def decode_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def unwrap_tool_payload(value: Any) -> Any:
    decoded = decode_jsonish(value)
    if (
        isinstance(decoded, dict)
        and decoded.get("ok") is True
        and "data" in decoded
    ):
        return decoded["data"]
    return decoded


REST_ROUTES: dict[str, tuple[str, str]] = {
    "bash": ("POST", "/tools/bash"),
    "environment_info": ("GET", "/tools/environment_info"),
    "read": ("POST", "/tools/read"),
    "search": ("POST", "/tools/search"),
    "workspace_search": ("POST", "/tools/workspace_search"),
    "fetch": ("POST", "/tools/fetch"),
    "list_files": ("POST", "/tools/list_files"),
    "tree_view": ("POST", "/tools/tree"),
    "glob_search": ("POST", "/tools/glob"),
    "write_file": ("POST", "/tools/write_file"),
    "edit_lines": ("POST", "/tools/edit_lines"),
    "delete_file_or_dir": ("POST", "/tools/delete"),
    "apply_patch": ("POST", "/tools/apply_patch"),
    "create_file_link": ("POST", "/tools/file_link/create"),
    "list_file_links": ("GET", "/tools/file_link/list"),
    "revoke_file_link": ("POST", "/tools/file_link/revoke"),
    "secret_scan": ("POST", "/tools/secret_scan"),
    "run_python_code": ("POST", "/tools/run_python_code"),
    "list_persistent_shells": ("GET", "/tools/list_persistent_shells"),
    "send_persistent_shell_input": (
        "POST",
        "/tools/send_persistent_shell_input",
    ),
    "read_persistent_shell_output": (
        "POST",
        "/tools/read_persistent_shell_output",
    ),
    "kill_persistent_shell": ("POST", "/tools/kill_persistent_shell"),
    "read_todos": ("GET", "/tools/todo"),
    "write_todos": ("POST", "/tools/todo"),
}


@dataclass
class RestToolClient:
    base_url: str

    async def list_tools(self) -> set[str]:
        return set(REST_ROUTES)

    async def call_tool(
        self, name: str, args: dict[str, Any] | None = None
    ) -> Any:
        method, path = REST_ROUTES[name]
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=20
        ) as client:
            if method == "GET":
                response = await client.get(path)
            else:
                response = await client.post(path, json=args or {})
        response.raise_for_status()
        return unwrap_tool_payload(response.json())


class McpSessionToolClient:
    def __init__(self, session: ClientSession):
        self._session = session

    async def list_tools(self) -> set[str]:
        result = await self._session.list_tools()
        return {tool.name for tool in result.tools}

    async def call_tool_result(
        self, name: str, args: dict[str, Any] | None = None
    ) -> Any:
        return await self._session.call_tool(name, args or {})

    async def call_tool(
        self, name: str, args: dict[str, Any] | None = None
    ) -> Any:
        result = await self.call_tool_result(name, args)
        error_text = (
            getattr(result.content[0], "text", "") if result.content else ""
        )
        assert not result.isError, error_text
        assert result.content
        text = getattr(result.content[0], "text", "")
        return unwrap_tool_payload(text)


@asynccontextmanager
async def streamable_http_tool_client(
    base_url: str,
) -> AsyncGenerator[McpSessionToolClient]:
    async with (
        httpx.AsyncClient(timeout=20) as client,
        streamable_http_client(f"{base_url}/mcp", http_client=client) as (
            read,
            write,
            _,
        ),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield McpSessionToolClient(session)


@asynccontextmanager
async def stdio_tool_client(
    tmp_path: Path,
) -> AsyncGenerator[tuple[McpSessionToolClient, Path]]:
    workspace = tmp_path / "workspace-stdio"
    workspace.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "local_shell_mcp.main",
            "--mode",
            "stdio",
            "--auth-mode",
            "none",
            "--workspace-root",
            str(workspace),
            "--agent-bridge-enabled",
            "false",
            "--remote-enabled",
            "false",
        ],
        cwd=str(PROJECT_ROOT),
        env=server_env(workspace, mode="stdio"),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield McpSessionToolClient(session), workspace


async def assert_required_tools(client: ToolClient, required: set[str]) -> None:
    tools = await client.list_tools()
    missing = required - tools
    assert not missing, f"missing tools: {sorted(missing)}"


pytestmark = pytest.mark.integration
