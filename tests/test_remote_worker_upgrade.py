import hashlib
import io
import json
import os
import subprocess
import sys
import sysconfig
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient


def _configure_remote_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_shell_mcp.config.settings import clear_settings_cache

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S", "1")
    clear_settings_cache()


async def _registered_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from local_shell_mcp.remote.manager import RemoteManager

    _configure_remote_state(tmp_path, monkeypatch)
    manager = RemoteManager()
    invite = await manager.create_invite(name="worker-a")
    registered = await manager.register_worker(
        {
            "invite": invite.code,
            "workdir": str(tmp_path),
            "capabilities": ["shell"],
            "info": {"hostname": "edge"},
        }
    )
    return manager, registered


def _poll_report(*, digest: str, version: str = "3.9.1") -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "worker_version": version,
        "bundle_version": version,
        "bundle_sha256": digest,
    }


@pytest.mark.asyncio
async def test_poll_mismatch_records_report_and_does_not_dequeue(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote.bundle import worker_bundle_manifest

    manager, registered = await _registered_manager(tmp_path, monkeypatch)
    worker = manager.workers[registered["name"]]
    worker.queue.put_nowait({"id": "job-1", "tool": "read", "args": {}})

    result = await manager.poll(
        registered["token"], _poll_report(digest="0" * 64)
    )

    manifest = worker_bundle_manifest()
    assert result == {
        "job": None,
        "upgrade": {
            "required": True,
            "version": manifest["bundle_version"],
            "sha256": manifest["sha256"],
            "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
        },
        "poll_timeout_s": 1.0,
    }
    assert worker.queue.qsize() == 1
    assert worker.info["poll_protocol_version"] == 1
    assert worker.info["lsm_version"] == "3.9.1"
    assert worker.info["worker_bundle_sha256"] == "0" * 64
    persisted = json.loads(manager._registry_path().read_text(encoding="utf-8"))
    assert persisted["workers"][0]["info"]["poll_protocol_version"] == 1
    assert registered["token"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_poll_matching_digest_delivers_job(tmp_path, monkeypatch):
    from local_shell_mcp.remote.bundle import worker_bundle_manifest

    manager, registered = await _registered_manager(tmp_path, monkeypatch)
    job = {"id": "job-1", "tool": "read", "args": {}}
    manager.workers[registered["name"]].queue.put_nowait(job)
    manifest = worker_bundle_manifest()

    result = await manager.poll(
        registered["token"],
        _poll_report(
            digest=str(manifest["sha256"]),
            version=str(manifest["bundle_version"]),
        ),
    )

    assert result["job"] == job
    assert result["upgrade"] == {
        "required": False,
        "version": manifest["bundle_version"],
        "sha256": manifest["sha256"],
        "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
    }


@pytest.mark.asyncio
async def test_poll_legacy_and_protocol_zero_remain_compatible(
    tmp_path, monkeypatch
):
    manager, registered = await _registered_manager(tmp_path, monkeypatch)
    worker = manager.workers[registered["name"]]
    worker.queue.put_nowait({"id": "legacy"})
    legacy = await manager.poll(registered["token"])
    assert legacy == {"job": {"id": "legacy"}, "poll_timeout_s": 1.0}

    worker.queue.put_nowait({"id": "v0"})
    protocol_zero = await manager.poll(
        registered["token"], {"protocol_version": 0}
    )
    assert protocol_zero == {"job": {"id": "v0"}, "poll_timeout_s": 1.0}
    assert worker.info["poll_protocol_version"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, message",
    [
        ({"protocol_version": True}, "must be an integer"),
        ({"protocol_version": 2}, "unsupported"),
        ({"protocol_version": 1}, "worker_version is required"),
        (
            {"protocol_version": 1, "worker_version": 3},
            "worker_version must be a string",
        ),
        (
            {
                "protocol_version": 1,
                "worker_version": "3.9.1",
                "bundle_sha256": "bad",
            },
            "bundle_sha256 is invalid",
        ),
    ],
)
async def test_poll_rejects_malformed_reports(
    tmp_path, monkeypatch, payload, message
):
    manager, registered = await _registered_manager(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=message):
        await manager.poll(registered["token"], payload)


def test_poll_endpoint_accepts_empty_body_and_rejects_non_object(monkeypatch):
    from local_shell_mcp.remote import http

    calls = []

    class Manager:
        async def poll(self, token, payload):
            calls.append((token, payload))
            return {"job": None, "heartbeat": True}

    monkeypatch.setattr(http, "remote_manager", lambda: Manager())
    client = TestClient(Starlette(routes=http.remote_routes()))
    authorization = "B" + "earer worker-token"

    response = client.post(
        "/remote/poll", headers={"Authorization": authorization}
    )
    assert response.status_code == 200
    assert calls == [("worker-token", {})]

    malformed = client.post(
        "/remote/poll",
        content=b"[]",
        headers={"Authorization": authorization},
    )
    assert malformed.status_code == 400
    assert "JSON object" in malformed.json()["message"]


def test_worker_bundle_manifest_is_deterministic_bounded_and_no_store():
    from local_shell_mcp.remote import bundle
    from local_shell_mcp.remote.http import remote_routes

    bundle.worker_bundle_bytes.cache_clear()
    bundle.worker_bundle_manifest.cache_clear()
    first = bundle.worker_bundle_bytes()
    bundle.worker_bundle_bytes.cache_clear()
    second = bundle.worker_bundle_bytes()
    manifest = bundle.worker_bundle_manifest()

    assert first == second
    assert manifest["sha256"] == hashlib.sha256(first).hexdigest()
    assert manifest["size"] == len(first)
    assert manifest["url"].endswith(f"?sha256={manifest['sha256']}")

    client = TestClient(Starlette(routes=remote_routes()))
    manifest_response = client.get("/remote/worker-bundle.tgz?manifest=1")
    bundle_response = client.get(str(manifest["url"]))
    assert manifest_response.status_code == 200
    assert manifest_response.headers["cache-control"] == "no-store"
    assert bundle_response.headers["cache-control"] == "no-store"
    assert bundle_response.content == first


def test_worker_bundle_keeps_strict_runtime_allowlist():
    from local_shell_mcp.remote.bundle import worker_bundle_bytes

    with tarfile.open(
        fileobj=io.BytesIO(worker_bundle_bytes()), mode="r:gz"
    ) as tar:
        names = set(tar.getnames())

    assert "local_shell_mcp/remote_worker/runtime.py" in names
    assert "local_shell_mcp/remote_worker/lifecycle.py" in names
    assert "local_shell_mcp/remote_worker/profiles.py" in names
    assert "local_shell_mcp/remote_worker/state.py" in names
    assert "local_shell_mcp/remote_worker/worker.py" in names
    assert "local_shell_mcp/audit/__init__.py" in names
    assert "local_shell_mcp/audit/core.py" in names
    assert "local_shell_mcp/audit/payloads.py" in names
    assert "local_shell_mcp/ops/patch/__init__.py" in names
    assert "local_shell_mcp/ops/patch/envelope.py" in names
    assert "local_shell_mcp/version.py" in names
    assert "local_shell_mcp/terminal/__init__.py" in names
    assert "local_shell_mcp/terminal/conpty.py" in names
    assert "local_shell_mcp/telemetry/__init__.py" in names
    assert "local_shell_mcp/telemetry/system.py" in names
    assert "local_shell_mcp/ui/__init__.py" in names
    assert "local_shell_mcp/ui/contracts.py" in names
    assert "local_shell_mcp/ui/dashboard.py" in names
    assert "local_shell_mcp/terminal/bridge.py" in names
    assert "local_shell_mcp/terminal/contracts.py" in names
    assert "local_shell_mcp/terminal/tmux.py" in names
    assert "local_shell_mcp/ops/agent.py" in names
    assert "local_shell_mcp/agent_bridge/skills.py" in names
    assert "local_shell_mcp/agent_bridge/sources.py" in names
    assert "local_shell_mcp/agent_bridge/models.py" in names
    assert "local_shell_mcp/jobs/runtime.py" in names
    assert "local_shell_mcp/persistence/__init__.py" in names
    assert "local_shell_mcp/persistence/store.py" in names
    assert "local_shell_mcp/agent_bridge/status.py" not in names
    assert "local_shell_mcp/config/cli.py" not in names
    assert "local_shell_mcp/jobs/cli.py" not in names
    assert not any(name.startswith("local_shell_mcp/tools/") for name in names)
    assert "local_shell_mcp/schemas/result_models/version.py" not in names
    assert "local_shell_mcp/utils/path_locks.py" in names
    assert "local_shell_mcp/utils/private_files.py" in names
    assert "local_shell_mcp/utils/processes.py" in names
    assert "local_shell_mcp/remote/manager.py" not in names
    assert "local_shell_mcp/remote/http.py" not in names
    assert "local_shell_mcp/remote/service.py" not in names
    assert not any(
        name.startswith("local_shell_mcp/ui/static/")
        or "ui_static" in name
        or name.startswith("tests/")
        for name in names
    )


def test_worker_bundle_imports_without_checkout_fallback(tmp_path):
    from local_shell_mcp.remote.bundle import worker_bundle_bytes

    archive = tmp_path / "worker.tgz"
    runtime = tmp_path / "runtime"
    archive.write_bytes(worker_bundle_bytes())
    with tarfile.open(archive, mode="r:gz") as tar:
        tar.extractall(runtime, filter="data")

    paths = sysconfig.get_paths()
    dependencies = sorted({paths["purelib"], paths["platlib"]})
    modules = [
        "local_shell_mcp.remote_worker.__main__",
        "local_shell_mcp.audit",
        "local_shell_mcp.telemetry.system",
        "local_shell_mcp.ui.dashboard",
        "local_shell_mcp.terminal.bridge",
        "local_shell_mcp.terminal.tmux",
        "local_shell_mcp.ops.session",
        "local_shell_mcp.persistence",
        "local_shell_mcp.persistence.store",
        "local_shell_mcp.ops.agent",
        "local_shell_mcp.agent_bridge.sources",
        "local_shell_mcp.schemas.result_models.agent",
        "local_shell_mcp.ops.shell",
        "local_shell_mcp.jobs.runtime",
        "local_shell_mcp.ops.todo",
        "local_shell_mcp.ops.files",
        "local_shell_mcp.ops.read",
        "local_shell_mcp.ops.search",
        "local_shell_mcp.ops.secret_scan",
        "local_shell_mcp.ops.transfer",
    ]
    code = """
import importlib
import json
import sys

runtime, dependencies, modules = sys.argv[1:]
sys.path[:] = [runtime, *json.loads(dependencies), *[
    item for item in sys.path
    if item and "site-packages" not in item and "local-shell-mcp" not in item
]]
for name in json.loads(modules):
    importlib.import_module(name)
print("worker-bundle-imports-ok")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            code,
            str(runtime),
            json.dumps(dependencies),
            json.dumps(modules),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "worker-bundle-imports-ok"


def _runtime_archive_bytes(
    *, extra_members: list[tarfile.TarInfo] | None = None
) -> bytes:
    from local_shell_mcp.remote_worker import runtime

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relative in runtime._REQUIRED_RUNTIME_FILES:
            payload = f"# {relative}\n".encode()
            info = tarfile.TarInfo(relative)
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))
        for info in extra_members or []:
            data = b"x" if info.isreg() else None
            if data is not None:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


@pytest.mark.parametrize("kind", ["traversal", "symlink", "hardlink"])
def test_safe_extract_rejects_unsafe_archive_members(tmp_path, kind):
    from local_shell_mcp.remote_worker import runtime

    if kind == "traversal":
        member = tarfile.TarInfo("../escape.py")
    elif kind == "symlink":
        member = tarfile.TarInfo("local_shell_mcp/link.py")
        member.type = tarfile.SYMTYPE
        member.linkname = "/tmp/target"
    else:
        member = tarfile.TarInfo("local_shell_mcp/hard.py")
        member.type = tarfile.LNKTYPE
        member.linkname = "local_shell_mcp/__init__.py"
    archive = tmp_path / "worker.tgz"
    archive.write_bytes(_runtime_archive_bytes(extra_members=[member]))

    with pytest.raises(ValueError, match="unsafe|unsupported"):
        runtime.safe_extract_bundle(archive, tmp_path / "runtime")
    assert not (tmp_path / "escape.py").exists()


def test_fetch_bytes_bypasses_cache_and_rejects_cross_origin(monkeypatch):
    from local_shell_mcp.remote_worker import runtime

    captured = {}

    class Response:
        headers = {"Content-Length": "2"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "https://controller.test/bundle"

        def read(self, size):
            captured["read_size"] = size
            return b"ok"

    class Opener:
        def open(self, request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *handlers: Opener()
    )
    result = runtime._fetch_bytes(
        "https://controller.test/bundle",
        server="https://controller.test",
        timeout=12,
        max_bytes=2,
    )
    request = captured["request"]
    assert result == b"ok"
    assert request.get_header("Cache-control") == "no-cache"
    assert request.get_header("Pragma") == "no-cache"
    assert request.get_header("User-agent") == (
        f"local-shell-mcp-worker/{runtime.__version__}"
    )
    assert captured["read_size"] == 3

    with pytest.raises(ValueError, match="controller origin"):
        runtime._fetch_bytes(
            "https://attacker.test/bundle",
            server="https://controller.test",
            timeout=12,
            max_bytes=2,
        )


def test_worker_update_redirect_preserves_user_agent_and_origin():
    from local_shell_mcp.remote_worker import runtime

    user_agent = f"local-shell-mcp-worker/{runtime.__version__}"
    request = urllib.request.Request(
        "https://controller.test/manifest",
        headers={"User-Agent": user_agent},
    )
    handler = runtime._SameOriginRedirectHandler("https://controller.test")

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "/bundle",
    )
    assert redirected is not None
    assert redirected.full_url == "https://controller.test/bundle"
    assert redirected.get_header("User-agent") == user_agent

    with pytest.raises(ValueError, match="controller origin"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.test/bundle",
        )


def test_manifest_requires_matching_version_digest_and_same_origin(monkeypatch):
    from local_shell_mcp.remote_worker import runtime

    digest = "a" * 64

    def payload(manifest):
        return json.dumps(manifest).encode()

    monkeypatch.setattr(
        runtime,
        "_fetch_bytes",
        lambda *args, **kwargs: payload(
            {
                "schema_version": 1,
                "bundle_version": "3.9.1",
                "sha256": digest,
                "size": 10,
                "url": f"/remote/worker-bundle.tgz?sha256={digest}",
            }
        ),
    )
    manifest = runtime.fetch_manifest(
        "https://controller.test",
        manifest_path="/remote/worker-bundle.tgz?manifest=1",
        expected_version="3.9.1",
        expected_digest=digest,
    )
    assert manifest["url"].startswith("https://controller.test/")

    with pytest.raises(ValueError, match="does not match"):
        runtime.fetch_manifest(
            "https://controller.test",
            manifest_path="/remote/worker-bundle.tgz?manifest=1",
            expected_version="3.9.2",
            expected_digest=digest,
        )

    monkeypatch.setattr(
        runtime,
        "_fetch_bytes",
        lambda *args, **kwargs: payload(
            {
                "schema_version": 1,
                "bundle_version": "3.9.1",
                "sha256": digest,
                "size": 10,
                "url": f"https://attacker.test/bundle?sha256={digest}",
            }
        ),
    )
    with pytest.raises(ValueError, match="controller origin"):
        runtime.fetch_manifest(
            "https://controller.test",
            manifest_path="/remote/worker-bundle.tgz?manifest=1",
            expected_version="3.9.1",
            expected_digest=digest,
        )


def _mock_runtime_download(monkeypatch, payload: bytes, version: str):
    from local_shell_mcp.remote_worker import runtime

    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        runtime,
        "fetch_manifest",
        lambda *args, **kwargs: {
            "schema_version": 1,
            "bundle_version": version,
            "sha256": digest,
            "size": len(payload),
            "url": f"https://controller.test/bundle?sha256={digest}",
        },
    )
    monkeypatch.setattr(
        runtime, "_fetch_bytes", lambda *args, **kwargs: payload
    )
    return digest


def test_install_runtime_is_transactional_and_short_circuits(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    payload = _runtime_archive_bytes()
    digest = _mock_runtime_download(monkeypatch, payload, "3.9.1")
    instruction = {
        "version": "3.9.1",
        "sha256": digest,
        "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
    }

    installed = runtime.install_runtime(
        "https://controller.test", instruction, current_version="3.9.0"
    )
    assert installed["updated"] is True
    assert runtime.runtime_identity(digest) == {
        "sha256": digest,
        "bundle_version": "3.9.1",
    }
    assert (
        runtime.worker_runtime_dir_for_digest(digest)
        / "local_shell_mcp/remote_worker/worker.py"
    ).is_file()

    monkeypatch.setattr(
        runtime,
        "fetch_manifest",
        lambda *args, **kwargs: pytest.fail("downloaded"),
    )
    same = runtime.install_runtime(
        "https://controller.test", instruction, current_version="3.9.1"
    )
    assert same["updated"] is False


def test_install_failure_restores_old_runtime_and_metadata(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    payload = _runtime_archive_bytes()
    digest = _mock_runtime_download(monkeypatch, payload, "3.9.1")
    old_runtime = runtime.worker_runtime_dir_for_digest(digest)
    old_runtime.mkdir(parents=True)
    (old_runtime / "old.txt").write_text("old", encoding="utf-8")
    old_metadata = b'{"old": true}'
    runtime.runtime_metadata_path(digest).write_bytes(old_metadata)
    monkeypatch.setattr(
        runtime,
        "_write_runtime_metadata",
        lambda data, digest=None: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        runtime.install_runtime(
            "https://controller.test",
            {
                "version": "3.9.1",
                "sha256": digest,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            },
            current_version="3.9.0",
        )

    assert (old_runtime / "old.txt").read_text(encoding="utf-8") == "old"
    assert runtime.runtime_metadata_path(digest).read_bytes() == old_metadata
    assert not list((tmp_path / "runtimes").glob("*.previous.*"))


def test_install_rejects_digest_mismatch_and_downgrade(tmp_path, monkeypatch):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    payload = _runtime_archive_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    corrupted = payload[:-1] + bytes([payload[-1] ^ 1])
    monkeypatch.setattr(
        runtime,
        "fetch_manifest",
        lambda *args, **kwargs: {
            "schema_version": 1,
            "bundle_version": "3.9.1",
            "sha256": digest,
            "size": len(payload),
            "url": f"https://controller.test/bundle?sha256={digest}",
        },
    )
    monkeypatch.setattr(
        runtime, "_fetch_bytes", lambda *args, **kwargs: corrupted
    )
    with pytest.raises(ValueError, match="checksum"):
        runtime.install_runtime(
            "https://controller.test",
            {
                "version": "3.9.1",
                "sha256": digest,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            },
            current_version="3.9.0",
        )

    with pytest.raises(ValueError, match="downgrade"):
        runtime.install_runtime(
            "https://controller.test",
            {
                "version": "3.9.0",
                "sha256": "b" * 64,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            },
            current_version="3.9.1",
        )


def test_reexec_argv_and_pythonpath_are_safe(tmp_path, monkeypatch):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    runtime_path = str(runtime.worker_runtime_dir())
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(["/old", runtime_path, "/old"]),
    )
    environment = runtime.reexec_environment()
    entries = environment["PYTHONPATH"].split(os.pathsep)
    assert entries == [runtime_path, "/old"]

    argv = runtime.worker_reexec_argv()
    assert argv == [
        sys.executable,
        "-m",
        "local_shell_mcp.remote_worker",
        "run",
    ]
    assert "--invite" not in argv
    assert "token" not in " ".join(argv).lower()


def test_reexec_uses_execve_on_posix_and_spawn_on_windows(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    captured = {}
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(
        runtime.os,
        "execve",
        lambda executable, argv, env: captured.update(
            executable=executable, argv=argv, env=env
        ),
    )
    runtime.reexec_worker()
    assert captured["argv"][0] == sys.executable
    assert captured["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(
        runtime.worker_runtime_dir()
    )

    spawned = {}
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda argv, **kwargs: spawned.update(argv=argv, kwargs=kwargs),
    )
    with pytest.raises(SystemExit) as exc_info:
        runtime.reexec_worker()
    assert exc_info.value.code == 0
    assert spawned["kwargs"]["close_fds"] is False


@pytest.mark.asyncio
async def test_worker_processes_required_upgrade_before_job(
    monkeypatch, tmp_path
):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        worker, "_configure_worker_runtime_env", lambda workdir: None
    )
    monkeypatch.setattr(
        worker,
        "_read_worker_identity",
        lambda server, name: {
            "server": server,
            "name": "worker-a",
            "access": "secret-access",
        },
    )
    monkeypatch.setattr(worker, "_write_worker_identity", lambda data: None)

    async def resume(*args, **kwargs):
        return {
            "ok": True,
            "data": {"name": "worker-a", "heartbeat_interval_s": 15},
        }

    poll_payloads = []

    async def post(
        url, payload, headers=None, timeout=None, operation="request"
    ):
        if url.endswith("/poll"):
            poll_payloads.append(payload)
            return {
                "ok": True,
                "data": {
                    "upgrade": {
                        "required": True,
                        "version": "3.9.1",
                        "sha256": "a" * 64,
                        "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
                    },
                    "job": {"id": "must-not-run", "tool": "read", "args": {}},
                },
            }
        raise AssertionError(url)

    async def upgrade(*args, **kwargs):
        raise SystemExit(0)

    monkeypatch.setattr(worker, "_worker_resume_or_none", resume)
    monkeypatch.setattr(worker, "_worker_post_json_forever", post)
    monkeypatch.setattr(worker, "_install_and_reexec_worker", upgrade)
    monkeypatch.setattr(
        worker,
        "execute_worker_tool",
        lambda *args, **kwargs: pytest.fail("job executed before upgrade"),
    )

    with pytest.raises(SystemExit):
        await worker.run_worker(
            "https://controller.test", "", "worker-a", str(tmp_path)
        )
    assert poll_payloads[0]["protocol_version"] == 1
    assert poll_payloads[0]["worker_version"]
    assert "secret-access" not in json.dumps(poll_payloads)


@pytest.mark.asyncio
async def test_upgrade_retry_is_capped_and_resets_after_successful_poll(
    monkeypatch, tmp_path
):
    import local_shell_mcp.remote_worker.worker as worker

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        worker, "_configure_worker_runtime_env", lambda workdir: None
    )
    monkeypatch.setattr(
        worker,
        "_read_worker_identity",
        lambda server, name: {
            "server": server,
            "name": "worker-a",
            "access": "access",
        },
    )
    monkeypatch.setattr(worker, "_write_worker_identity", lambda data: None)

    async def resume(*args, **kwargs):
        return {"ok": True, "data": {"name": "worker-a"}}

    responses = iter(
        [
            {"upgrade": {"required": True}},
            {"upgrade": {"required": False}, "job": None},
            {"upgrade": {"required": True}},
            {"upgrade": {"required": True}},
        ]
    )

    async def post(
        url, payload, headers=None, timeout=None, operation="request"
    ):
        return {"ok": True, "data": next(responses)}

    attempts = 0

    async def upgrade(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            raise SystemExit(0)
        raise RuntimeError("broken package")

    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(worker, "_worker_resume_or_none", resume)
    monkeypatch.setattr(worker, "_worker_post_json_forever", post)
    monkeypatch.setattr(worker, "_install_and_reexec_worker", upgrade)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)

    with pytest.raises(SystemExit):
        await worker.run_worker(
            "https://controller.test", "", "worker-a", str(tmp_path)
        )
    assert sleeps == [1.0, 1.0]
    assert worker._worker_retry_delay(100) == 30.0


def test_join_script_installs_persistent_verified_runtime():
    from importlib import resources

    script = (
        resources.files("local_shell_mcp.remote")
        .joinpath("join_worker.sh")
        .read_text(encoding="utf-8")
    )
    assert 'RUNTIME_DIR="$STATE_DIR/runtimes/$RUNTIME_DIGEST"' in script
    assert 'RUNTIME_METADATA="$RUNTIME_DIR/runtime.json"' in script
    assert 'LAUNCHER="$STATE_DIR/run"' in script
    assert "prepare_profile" in script
    assert "configure_runtime" in script
    assert "runtime_is_installed" in script
    assert "write_profile_metadata" in script
    assert "install_launcher" in script
    assert "Reusing worker runtime" in script
    assert "?manifest=1" in script
    assert "Cache-Control: no-cache" in script
    assert "sha256" in script
    assert "member.isreg()" in script
    assert "os.replace(staging, runtime)" in script
    assert (
        'export LOCAL_SHELL_MCP_WORKER_RUNTIME_SHA256="$RUNTIME_DIGEST"'
        in script
    )
    assert (
        'export PYTHONPATH="$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}"' in script
    )
    assert 'ARGS=(connect --server "$SERVER" --invite "$INVITE"' in script
    assert '--profile "$PROFILE_ID"' in script
    assert 'run "$PROFILE_ID"' in script
    assert '"$PROFILE_DIR/worker.log"' in script
    assert '"runtime_sha256": digest' in script
    assert "--persist" not in script
    assert "ARGS=(--server" not in script
    assert 'rm -rf "$RUNTIME_DIR"' not in script


def test_join_script_reuses_one_digest_runtime_across_profiles(tmp_path):
    from importlib import resources

    from local_shell_mcp.remote.bundle import (
        worker_bundle_bytes,
        worker_bundle_manifest,
    )

    script = (
        resources.files("local_shell_mcp.remote")
        .joinpath("join_worker.sh")
        .read_text(encoding="utf-8")
        .replace("__REMOTE_SERVER__", "https://controller.test")
        .replace(
            "__REMOTE_WORKER_BUNDLE_PATH__",
            "/remote/worker-bundle.tgz",
        )
    )
    original_tail = '\n  start_worker\n}\n\nmain "$@"'
    assert original_tail in script
    script = script.replace(
        original_tail,
        '\n  echo bootstrap-complete\n}\n\nmain "$@"',
    )
    join_path = tmp_path / "join.sh"
    join_path.write_text(script, encoding="utf-8")
    join_path.chmod(0o700)

    bundle = worker_bundle_bytes()
    manifest = worker_bundle_manifest()
    bundle_path = tmp_path / "worker.tgz"
    manifest_path = tmp_path / "manifest.json"
    bundle_path.write_bytes(bundle)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    requests_path = tmp_path / "curl-requests.txt"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import shutil\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "output = args[args.index('-o') + 1]\n"
        "url = next(item for item in args if item.startswith('http'))\n"
        "with open(os.environ['FAKE_CURL_REQUESTS'], 'a', encoding='utf-8') as log:\n"
        "    log.write(url + '\\n')\n"
        "source = os.environ['FAKE_MANIFEST'] if 'manifest=1' in url else os.environ['FAKE_BUNDLE']\n"
        "shutil.copyfile(source, output)\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o700)

    state_dir = tmp_path / "state"
    environment = {
        **os.environ,
        "PATH": os.pathsep.join((str(bin_dir), os.environ["PATH"])),
        "LOCAL_SHELL_MCP_WORKER_STATE_DIR": str(state_dir),
        "FAKE_CURL_REQUESTS": str(requests_path),
        "FAKE_MANIFEST": str(manifest_path),
        "FAKE_BUNDLE": str(bundle_path),
    }
    for profile_id in ("p_abcdefgh", "p_ijklmnop"):
        completed = subprocess.run(
            [
                "bash",
                str(join_path),
                "--invite",
                "fixture-invite",
                "--profile",
                profile_id,
                "--workdir",
                str(tmp_path),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "bootstrap-complete" in completed.stdout

    requests = requests_path.read_text(encoding="utf-8").splitlines()
    assert sum("manifest=1" in request for request in requests) == 2
    assert sum("sha256=" in request for request in requests) == 1
    digest = str(manifest["sha256"])
    runtime = state_dir / "runtimes" / digest
    assert (runtime / "runtime.json").is_file()
    assert (
        len(
            [
                path
                for path in (state_dir / "runtimes").iterdir()
                if path.is_dir()
            ]
        )
        == 1
    )
    for profile_id in ("p_abcdefgh", "p_ijklmnop"):
        profile = json.loads(
            (state_dir / "profiles" / profile_id / "profile.json").read_text(
                encoding="utf-8"
            )
        )
        assert profile["runtime_sha256"] == digest
    assert (state_dir / "run").stat().st_mode & 0o111


def test_bundle_rejects_stale_digest_and_retry_logs_redact_secrets(capsys):
    from local_shell_mcp.remote import bundle
    from local_shell_mcp.remote.http import remote_routes
    from local_shell_mcp.remote_worker import worker

    client = TestClient(Starlette(routes=remote_routes()))
    response = client.get("/remote/worker-bundle.tgz?sha256=" + "0" * 64)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"

    fixture_value = "fixture-value"
    error = RuntimeError(
        "download https://controller.test/bundle?"
        + "to"
        + "ken="
        + fixture_value
        + " failed; "
        + "Author"
        + "ization: B"
        + "earer "
        + fixture_value
    )
    worker._worker_log_retry("upgrade", error, 1)
    stderr = capsys.readouterr().err
    assert fixture_value not in stderr
    assert "<redacted>" in stderr
    assert bundle.worker_bundle_manifest()["sha256"] not in response.text


def test_fetch_latest_manifest_revalidates_stable_identity(monkeypatch):
    from local_shell_mcp.remote_worker import runtime

    digest = "a" * 64
    initial = json.dumps({"bundle_version": "3.9.1", "sha256": digest}).encode()
    monkeypatch.setattr(
        runtime, "_fetch_bytes", lambda *args, **kwargs: initial
    )
    calls = []

    def fetch_manifest(server, **kwargs):
        calls.append((server, kwargs))
        return {"bundle_version": "3.9.1", "sha256": digest}

    monkeypatch.setattr(runtime, "fetch_manifest", fetch_manifest)

    result = runtime.fetch_latest_manifest("https://controller.test")

    assert result["sha256"] == digest
    assert calls == [
        (
            "https://controller.test",
            {
                "manifest_path": runtime.REMOTE_WORKER_MANIFEST_PATH,
                "expected_version": "3.9.1",
                "expected_digest": digest,
            },
        )
    ]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "manifest JSON"),
        (b"[]", "invalid remote worker manifest"),
        (
            json.dumps({"bundle_version": "", "sha256": "bad"}).encode(),
            "invalid identity",
        ),
    ],
)
def test_fetch_latest_manifest_rejects_invalid_bootstrap_identity(
    monkeypatch, payload, message
):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setattr(
        runtime, "_fetch_bytes", lambda *args, **kwargs: payload
    )
    monkeypatch.setattr(
        runtime,
        "fetch_manifest",
        lambda *args, **kwargs: pytest.fail("revalidated invalid identity"),
    )

    with pytest.raises(ValueError, match=message):
        runtime.fetch_latest_manifest("https://controller.test")


def test_install_runtime_force_reinstalls_matching_digest(
    tmp_path, monkeypatch
):
    from local_shell_mcp.remote_worker import runtime

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    payload = _runtime_archive_bytes()
    digest = _mock_runtime_download(monkeypatch, payload, "3.9.1")
    instruction = {
        "version": "3.9.1",
        "sha256": digest,
        "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
    }
    runtime.install_runtime(
        "https://controller.test", instruction, current_version="3.9.0"
    )

    second = runtime.install_runtime(
        "https://controller.test",
        instruction,
        current_version="3.9.1",
        force=True,
    )

    assert second["updated"] is True
    assert second["sha256"] == digest
