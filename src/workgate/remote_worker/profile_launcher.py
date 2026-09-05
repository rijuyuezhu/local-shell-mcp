"""Stable credential-free launchers for independently runnable worker profiles."""

import contextlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

from ..utils.private_files import atomic_write_private_text
from .state import (
    worker_launcher_path,
    worker_launcher_runner_path,
    worker_profile_dir,
    worker_python_path,
)

_REQUIRED_RUNTIME_FILES = (
    "workgate/__init__.py",
    "workgate/remote_worker/__init__.py",
    "workgate/remote_worker/__main__.py",
    "workgate/remote_worker/compat.py",
    "workgate/remote_worker/identity.py",
    "workgate/remote_worker/lifecycle.py",
    "workgate/remote_worker/profile_launcher.py",
    "workgate/remote_worker/profiles.py",
    "workgate/remote_worker/state.py",
    "workgate/remote_worker/worker.py",
)


def profile_reconnect_command(profile_id: str) -> str:
    """Return the target-platform command for one validated profile."""
    worker_profile_dir(profile_id)
    argv = [str(worker_launcher_path()), profile_id]
    return (
        subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    )


def _runner_text() -> str:
    required = repr(_REQUIRED_RUNTIME_FILES)
    return f"""\
import json
import os
import re
import sys
from pathlib import Path

state_dir = Path(__file__).resolve().parent
if len(sys.argv) != 2 or not re.fullmatch(r"p_[A-Za-z0-9_-]{{8,64}}", sys.argv[1]):
    raise SystemExit(f"usage: {{sys.argv[0]}} PROFILE_ID")
profile_id = sys.argv[1]
profile_path = state_dir / "profiles" / profile_id / "profile.json"
try:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
except (OSError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit(f"worker profile is unreadable: {{profile_id}}") from exc
if (
    not isinstance(profile, dict)
    or profile.get("schema_version") != 1
    or profile.get("profile_id") != profile_id
):
    raise SystemExit(f"worker profile is invalid: {{profile_id}}")
digest = profile.get("runtime_sha256")
if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{{64}}", digest):
    raise SystemExit(f"worker profile runtime is invalid: {{profile_id}}")
runtime = state_dir / "runtimes" / digest
metadata_path = runtime / "runtime.json"
try:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
except (OSError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit("stored worker runtime metadata is unavailable") from exc
required = {required}
if (
    not isinstance(metadata, dict)
    or metadata.get("schema_version") != 1
    or metadata.get("sha256") != digest
    or not all((runtime / relative).is_file() for relative in required)
):
    raise SystemExit("stored worker runtime is incomplete or invalid")
os.environ["WORKGATE_WORKER_STATE_DIR"] = str(state_dir)
os.environ["WORKGATE_WORKER_PROFILE_ID"] = profile_id
os.environ["WORKGATE_WORKER_RUNTIME_SHA256"] = digest
sys.path.insert(0, str(runtime))
from workgate.remote_worker.compat import main
main(["run", profile_id])
"""


def _posix_launcher_text() -> str:
    return """\
#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
PYTHON_BIN=""
IFS= read -r PYTHON_BIN < "$STATE_DIR/python" || true
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "stored worker Python is unavailable; run a fresh invite command" >&2
  exit 1
fi
exec "$PYTHON_BIN" "$STATE_DIR/run.py" "$@"
"""


def _windows_launcher_text() -> str:
    return """@echo off\r
setlocal\r
set \"STATE_DIR=%~dp0\"\r
set \"PYTHON_BIN=\"\r
set /p PYTHON_BIN=<\"%STATE_DIR%python\"\r
if not defined PYTHON_BIN (\r
  echo stored worker Python is unavailable; run a fresh invite command 1>&2\r
  exit /b 1\r
)\r
\"%PYTHON_BIN%\" \"%STATE_DIR%run.py\" %*\r
"""


def ensure_profile_launcher(
    python_executable: str | Path | None = None,
) -> tuple[Path, bool]:
    """Install the stable profile launcher and report whether it changed."""
    executable = str(Path(python_executable or sys.executable).resolve())
    python_path = worker_python_path()
    runner_path = worker_launcher_runner_path()
    launcher_path = worker_launcher_path()
    launcher_text = (
        _windows_launcher_text() if os.name == "nt" else _posix_launcher_text()
    )
    desired = (
        (python_path, executable + "\n"),
        (runner_path, _runner_text()),
        (launcher_path, launcher_text),
    )
    changed = False
    for path, content in desired:
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if path.is_symlink() or current != content:
            atomic_write_private_text(path, content)
            changed = True
    if os.name != "nt":
        with contextlib.suppress(OSError):
            launcher_path.chmod(0o700)
    return launcher_path, changed
