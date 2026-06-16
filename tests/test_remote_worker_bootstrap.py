import builtins
import subprocess
import sys
import urllib.error
import urllib.request
from email.message import Message
from io import BytesIO

import pytest


def test_remote_worker_entrypoint_import_is_dependency_light():
    script = """
import builtins

blocked = {"fastapi", "httpx", "mcp", "starlette", "uvicorn"}
real_import = builtins.__import__


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] in blocked:
        raise AssertionError(f"unexpected bootstrap import: {name}")
    return real_import(name, globals, locals, fromlist, level)


builtins.__import__ = guarded_import
import local_shell_mcp.remote_worker
from local_shell_mcp.remote.worker import worker_capabilities, worker_info

assert "shell" in worker_capabilities()
assert worker_info(".")["workdir"] == "."
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=".",
        env={"PYTHONPATH": "src"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_execute_worker_tool_imports_registry_lazily(monkeypatch):
    import local_shell_mcp.remote.worker as worker

    real_import = builtins.__import__
    seen_mcp_import = False

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        nonlocal seen_mcp_import
        if name.split(".")[0] == "mcp":
            seen_mcp_import = True
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert "shell" in worker.worker_capabilities()
    assert seen_mcp_import is False


class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.body


def test_worker_post_json_posts_json_and_returns_object(monkeypatch):
    import local_shell_mcp.remote.worker as worker

    captured: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["content_type"] = request.get_header("Content-type")
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _FakeResponse(b'{"ok": true, "data": {"value": 1}}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = worker._worker_post_json(
        "https://example.test/remote/register",
        {"invite": "abc"},
        headers={"Authorization": "Bearer token"},
        timeout=30,
    )

    assert result == {"ok": True, "data": {"value": 1}}
    assert captured == {
        "url": "https://example.test/remote/register",
        "data": b'{"invite": "abc"}',
        "content_type": "application/json",
        "authorization": "Bearer token",
        "timeout": 30,
    }


def test_worker_post_json_rejects_non_object_response(monkeypatch):
    import local_shell_mcp.remote.worker as worker

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        return _FakeResponse(b'["not", "an", "object"]')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(
        RuntimeError, match="worker HTTP response was not a JSON object"
    ):
        worker._worker_post_json("https://example.test/remote/poll", {})


def test_worker_post_json_includes_http_error_detail(monkeypatch):
    import local_shell_mcp.remote.worker as worker

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=Message(),
            fp=BytesIO(b'{"message": "bad invite"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        worker._worker_post_json("https://example.test/remote/register", {})

    assert "worker HTTP request failed with 400" in str(exc_info.value)
    assert "bad invite" in str(exc_info.value)


def test_worker_post_json_wraps_url_errors(monkeypatch):
    import local_shell_mcp.remote.worker as worker

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(
        RuntimeError, match="worker HTTP request failed: connection refused"
    ):
        worker._worker_post_json("https://example.test/remote/poll", {})
