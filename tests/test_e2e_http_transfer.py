from __future__ import annotations

import hashlib
import os

import pytest

from tests.e2e_helpers import streamable_http_tool_client
from tests.test_e2e_remote_worker import (
    run_remote_enabled_mcp_process,
    start_worker_process,
    terminate_process,
    wait_for_machine,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _data(result):
    return result.get("data", result)


async def _enroll_worker(client, base_url, machine, workspace):
    invite = await client.call_tool(
        "remote_admin",
        {
            "action": "invite",
            "args": {"name": machine, "workdir": str(workspace), "ttl_s": 120},
        },
    )
    worker = start_worker_process(
        base_url, _data(invite)["code"], machine, workspace
    )
    await wait_for_machine(client, worker, machine, workspace)
    return worker


async def test_real_controller_worker_large_http_routes(tmp_path) -> None:
    payload = (b"phase-8-http-transfer-" * 60000) + b"tail"
    assert len(payload) > 1024 * 1024
    async with (
        run_remote_enabled_mcp_process(tmp_path) as (
            base_url,
            control_workspace,
            remote_workspace,
        ),
        streamable_http_tool_client(base_url) as client,
    ):
        worker = await _enroll_worker(
            client, base_url, "http-worker-one", remote_workspace
        )
        try:
            local = _data(
                await client.call_tool(
                    "session_start", {"target": "local", "workdir": "."}
                )
            )
            remote = _data(
                await client.call_tool(
                    "session_start",
                    {
                        "target": "remote",
                        "machine": "http-worker-one",
                        "workdir": ".",
                    },
                )
            )
            local_id = local["session_id"]
            remote_id = remote["session_id"]

            (control_workspace / "local-source.bin").write_bytes(payload)
            local_to_remote = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": local_id,
                        "src_path": "local-source.bin",
                        "dst_session_id": remote_id,
                        "dst_path": "from-local.bin",
                        "kind": "file",
                    },
                )
            )
            assert local_to_remote["transport"] == "http_stream"
            assert local_to_remote["bytes"] == len(payload)
            assert (
                local_to_remote["sha256"] == hashlib.sha256(payload).hexdigest()
            )
            assert (remote_workspace / "from-local.bin").read_bytes() == payload

            small_payload = b"small-control-channel-fallback"
            (control_workspace / "small-source.bin").write_bytes(small_payload)
            small_copy = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": local_id,
                        "src_path": "small-source.bin",
                        "dst_session_id": remote_id,
                        "dst_path": "small-destination.bin",
                        "kind": "file",
                    },
                )
            )
            assert small_copy["transport"] == "worker_rpc"
            assert (
                remote_workspace / "small-destination.bin"
            ).read_bytes() == small_payload

            directory_payload = os.urandom(1100000)
            local_directory = control_workspace / "local-directory"
            local_directory.mkdir()
            (local_directory / "payload.bin").write_bytes(directory_payload)
            directory_copy = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": local_id,
                        "src_path": "local-directory",
                        "dst_session_id": remote_id,
                        "dst_path": "remote-directory",
                        "kind": "dir",
                    },
                )
            )
            assert directory_copy["transport"] == "http_stream"
            assert (
                remote_workspace / "remote-directory" / "payload.bin"
            ).read_bytes() == directory_payload

            (remote_workspace / "remote-source.bin").write_bytes(payload[::-1])
            remote_to_local = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": remote_id,
                        "src_path": "remote-source.bin",
                        "dst_session_id": local_id,
                        "dst_path": "from-remote.bin",
                        "kind": "file",
                    },
                )
            )
            assert remote_to_local["transport"] == "http_stream"
            assert (
                control_workspace / "from-remote.bin"
            ).read_bytes() == payload[::-1]

            same_worker = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": remote_id,
                        "src_path": "remote-source.bin",
                        "dst_session_id": remote_id,
                        "dst_path": "same-worker.bin",
                        "kind": "file",
                    },
                )
            )
            assert same_worker["transport"] == "same_worker"
            assert (
                remote_workspace / "same-worker.bin"
            ).read_bytes() == payload[::-1]
        finally:
            terminate_process(worker)


async def test_real_two_workers_large_http_spool(tmp_path) -> None:
    payload = (b"cross-worker-http-" * 70000) + b"done"
    assert len(payload) > 1024 * 1024
    async with (
        run_remote_enabled_mcp_process(tmp_path) as (
            base_url,
            _control_workspace,
            first_workspace,
        ),
        streamable_http_tool_client(base_url) as client,
    ):
        second_workspace = tmp_path / "remote-workspace-two"
        second_workspace.mkdir(parents=True)
        first_worker = await _enroll_worker(
            client, base_url, "http-worker-source", first_workspace
        )
        second_worker = await _enroll_worker(
            client, base_url, "http-worker-destination", second_workspace
        )
        try:
            source = _data(
                await client.call_tool(
                    "session_start",
                    {
                        "target": "remote",
                        "machine": "http-worker-source",
                        "workdir": ".",
                    },
                )
            )
            destination = _data(
                await client.call_tool(
                    "session_start",
                    {
                        "target": "remote",
                        "machine": "http-worker-destination",
                        "workdir": ".",
                    },
                )
            )
            (first_workspace / "source.bin").write_bytes(payload)
            result = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": source["session_id"],
                        "src_path": "source.bin",
                        "dst_session_id": destination["session_id"],
                        "dst_path": "destination.bin",
                        "kind": "file",
                    },
                )
            )
            assert result["transport"] == "http_stream"
            assert result["bytes"] == len(payload)
            assert result["sha256"] == hashlib.sha256(payload).hexdigest()
            assert (
                second_workspace / "destination.bin"
            ).read_bytes() == payload

            directory_payload = os.urandom(1100000)
            source_directory = first_workspace / "source-directory"
            source_directory.mkdir()
            (source_directory / "payload.bin").write_bytes(directory_payload)
            directory_result = _data(
                await client.call_tool(
                    "session_copy",
                    {
                        "src_session_id": source["session_id"],
                        "src_path": "source-directory",
                        "dst_session_id": destination["session_id"],
                        "dst_path": "destination-directory",
                        "kind": "dir",
                    },
                )
            )
            assert directory_result["transport"] == "http_stream"
            assert (
                second_workspace / "destination-directory" / "payload.bin"
            ).read_bytes() == directory_payload
        finally:
            terminate_process(second_worker)
            terminate_process(first_worker)
