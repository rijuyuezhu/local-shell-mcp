"""Shared constants for remote worker coordination."""

from __future__ import annotations

REMOTE_JOIN_PATH = "/join"
REMOTE_API_PREFIX = "/remote"
REMOTE_WORKER_BUNDLE_PATH = "/remote/worker-bundle.tgz"
REMOTE_WORKER_DISTRIBUTIONS = (
    "mcp",
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "PyYAML",
    "Py" + "JWT",
    "httpx",
    "aiofiles",
    "python-multipart",
    "pathspec",
)
