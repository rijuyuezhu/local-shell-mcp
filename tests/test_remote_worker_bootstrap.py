import builtins
import subprocess
import sys


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
