#!/usr/bin/env bash
set -euo pipefail

SERVER=__REMOTE_SERVER__
BUNDLE_URL="$SERVER__REMOTE_WORKER_BUNDLE_PATH__"
INVITE=""
NAME=""
WORKDIR=""
PROFILE_ID=""
BACKGROUND=0
TMPDIR=""
PYTHON_BIN=""
UV_BIN=""
STATE_DIR="${LOCAL_SHELL_MCP_WORKER_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/local-shell-mcp-worker}"
RUNTIME_DIGEST=""
RUNTIME_VERSION=""
RUNTIME_DIR=""
RUNTIME_METADATA=""
LAUNCHER=""
PROFILE_DIR=""

usage() {
  cat >&2 <<'EOF'
usage: join_worker.sh --invite CODE [--name NAME] [--workdir PATH] [--profile ID] [--background]
EOF
}

die() {
  echo "$1" >&2
  exit "${2:-2}"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --invite) INVITE="${2:-}"; shift 2 ;;
      --name) NAME="${2:-}"; shift 2 ;;
      --workdir) WORKDIR="${2:-}"; shift 2 ;;
      --profile) PROFILE_ID="${2:-}"; shift 2 ;;
      --background) BACKGROUND=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) usage; die "unknown argument: $1" ;;
    esac
  done
  [ -n "$INVITE" ] || die "--invite is required"
  [ -n "$WORKDIR" ] || WORKDIR="$PWD"
}

cleanup() {
  if [ -n "$TMPDIR" ]; then
    rm -rf "$TMPDIR"
  fi
}

require_basic_tools() {
  have curl || die "curl is required"
}

python_supports_worker() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 14) else 1)
PY
}

find_existing_python() {
  local candidate
  for candidate in python3.14 python3; do
    if have "$candidate" && python_supports_worker "$candidate"; then
      PYTHON_BIN="$(command -v "$candidate")"
      return 0
    fi
  done
  return 1
}

download_temporary_uv() {
  mkdir -p "$TMPDIR/uv-bin"
  echo "uv not found; downloading a temporary uv into the worker state directory..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$TMPDIR/uv-bin" sh >/dev/null
  if [ -x "$TMPDIR/uv-bin/uv" ]; then
    UV_BIN="$TMPDIR/uv-bin/uv"
  elif [ -x "$TMPDIR/uv-bin/bin/uv" ]; then
    UV_BIN="$TMPDIR/uv-bin/bin/uv"
  else
    return 1
  fi
}

ensure_uv() {
  if have uv; then
    UV_BIN="$(command -v uv)"
    return 0
  fi
  download_temporary_uv
}

find_or_install_python() {
  if find_existing_python; then
    return 0
  fi

  if ensure_uv; then
    if ! PYTHON_BIN="$($UV_BIN python find 3.14 2>/dev/null)"; then
      echo "Python 3.14 not found; installing with uv..." >&2
      "$UV_BIN" python install 3.14 >/dev/null
      PYTHON_BIN="$($UV_BIN python find 3.14)"
    fi
  fi

  if [ -z "$PYTHON_BIN" ] || ! python_supports_worker "$PYTHON_BIN"; then
    die "python >= 3.14 is required; install python3.14 or uv and retry"
  fi
}

select_launcher_path() {
  LAUNCHER="$($PYTHON_BIN - "$STATE_DIR" <<'PY'
import os
import sys
from pathlib import Path

name = "run.cmd" if os.name == "nt" else "run"
print(Path(sys.argv[1]) / name)
PY
)"
}

prepare_profile() {
  if [ -z "$PROFILE_ID" ]; then
    while :; do
      PROFILE_ID="p_$($PYTHON_BIN -c 'import secrets; print(secrets.token_hex(8))')"
      [ ! -e "$STATE_DIR/profiles/$PROFILE_ID" ] && break
    done
  fi
  "$PYTHON_BIN" - "$PROFILE_ID" <<'PY'
import re
import sys

if not re.fullmatch(r"p_[A-Za-z0-9_-]{8,64}", sys.argv[1]):
    raise SystemExit("invalid remote worker profile id")
PY
  PROFILE_DIR="$STATE_DIR/profiles/$PROFILE_ID"
  if [ -f "$PROFILE_DIR/identity.json" ]; then
    die "worker profile already exists; reconnect with $LAUNCHER $PROFILE_ID"
  fi
  mkdir -p "$PROFILE_DIR"
  chmod 700 "$PROFILE_DIR" 2>/dev/null || true
}

install_launcher() {
  local installed_launcher
  installed_launcher="$(
    cd "$RUNTIME_DIR"
    LOCAL_SHELL_MCP_WORKER_STATE_DIR="$STATE_DIR" \
    PYTHONPATH="$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" - "$PYTHON_BIN" <<'PY'
import sys

from local_shell_mcp.remote_worker.profile_launcher import ensure_profile_launcher

launcher, _changed = ensure_profile_launcher(sys.argv[1])
print(launcher)
PY
  )"
  [ "$installed_launcher" = "$LAUNCHER" ] || die "worker launcher path mismatch"
}

download_manifest() {
  echo "Downloading worker manifest..." >&2
  curl -fSs \
    -H 'Cache-Control: no-cache' \
    -H 'Pragma: no-cache' \
    "$BUNDLE_URL?manifest=1" \
    -o "$TMPDIR/manifest.json"

  "$PYTHON_BIN" - "$SERVER" "$TMPDIR/manifest.json" "$TMPDIR" <<'PY'
import json
import re
import sys
import urllib.parse
from pathlib import Path

server, manifest_path, output_dir = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
    raise SystemExit("invalid worker manifest schema")
version = manifest.get("bundle_version")
digest = manifest.get("sha256")
size = manifest.get("size")
raw_url = manifest.get("url")
if not isinstance(version, str) or not version or len(version) > 128:
    raise SystemExit("invalid worker manifest version")
if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
    raise SystemExit("invalid worker manifest digest")
if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= 64 * 1024 * 1024:
    raise SystemExit("invalid worker manifest size")
if not isinstance(raw_url, str) or not raw_url:
    raise SystemExit("invalid worker manifest URL")


def origin(value: str) -> tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise SystemExit("worker bundle URL must use absolute HTTP(S)")
    return (
        parsed.scheme.lower(),
        parsed.hostname.lower(),
        parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
    )


url = urllib.parse.urljoin(server.rstrip("/") + "/", raw_url)
if origin(server) != origin(url):
    raise SystemExit("worker bundle URL must remain on controller origin")
query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
if query.get("sha256") != [digest]:
    raise SystemExit("worker bundle URL is not digest-qualified")
output = Path(output_dir)
(output / "bundle-url").write_text(url, encoding="utf-8")
(output / "bundle-version").write_text(version, encoding="utf-8")
(output / "bundle-sha256").write_text(digest, encoding="ascii")
(output / "bundle-size").write_text(str(size), encoding="ascii")
PY
}

configure_runtime() {
  RUNTIME_DIGEST="$(cat "$TMPDIR/bundle-sha256")"
  RUNTIME_VERSION="$(cat "$TMPDIR/bundle-version")"
  RUNTIME_DIR="$STATE_DIR/runtimes/$RUNTIME_DIGEST"
  RUNTIME_METADATA="$RUNTIME_DIR/runtime.json"
}

runtime_is_installed() {
  "$PYTHON_BIN" - \
    "$RUNTIME_DIR" \
    "$RUNTIME_METADATA" \
    "$RUNTIME_VERSION" \
    "$RUNTIME_DIGEST" <<'PY'
import json
import sys
from pathlib import Path

runtime_path, metadata_path, version, digest = sys.argv[1:]
runtime = Path(runtime_path)
metadata_file = Path(metadata_path)
try:
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
except (OSError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
required = (
    "local_shell_mcp/__init__.py",
    "local_shell_mcp/remote_worker/__init__.py",
    "local_shell_mcp/remote_worker/__main__.py",
    "local_shell_mcp/remote_worker/compat.py",
    "local_shell_mcp/remote_worker/identity.py",
    "local_shell_mcp/remote_worker/lifecycle.py",
    "local_shell_mcp/remote_worker/migration.py",
    "local_shell_mcp/remote_worker/profile_launcher.py",
    "local_shell_mcp/remote_worker/profiles.py",
    "local_shell_mcp/remote_worker/state.py",
    "local_shell_mcp/remote_worker/worker.py",
)
valid = (
    isinstance(metadata, dict)
    and metadata.get("schema_version") == 1
    and metadata.get("bundle_version") == version
    and metadata.get("sha256") == digest
    and all((runtime / relative).is_file() for relative in required)
)
raise SystemExit(0 if valid else 1)
PY
}

write_profile_metadata() {
  "$PYTHON_BIN" - \
    "$PROFILE_DIR/profile.json" \
    "$PROFILE_ID" \
    "$RUNTIME_DIGEST" \
    "$RUNTIME_VERSION" \
    "$SERVER" \
    "$NAME" \
    "$WORKDIR" <<'PY'
import contextlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

profile_path, profile_id, digest, version, server, name, workdir = sys.argv[1:]
if not re.fullmatch(r"p_[A-Za-z0-9_-]{8,64}", profile_id):
    raise SystemExit("invalid remote worker profile id")
if not re.fullmatch(r"[0-9a-f]{64}", digest):
    raise SystemExit("invalid remote worker runtime digest")
limits = {"runtime_version": 128, "server": 4096, "name": 512, "workdir": 4096}
values = {
    "runtime_version": version,
    "server": server,
    "name": name,
    "workdir": workdir,
}
for key, value in values.items():
    if len(value.encode("utf-8")) > limits[key] or any(ord(character) < 32 for character in value):
        raise SystemExit(f"worker profile {key} is invalid")
path = Path(profile_path)
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
try:
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": profile_id,
                "runtime_sha256": digest,
                **values,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with contextlib.suppress(OSError):
        temporary.chmod(0o600)
    os.replace(temporary, path)
    with contextlib.suppress(OSError):
        path.chmod(0o600)
finally:
    temporary.unlink(missing_ok=True)
PY
}

install_bundle() {
  echo "Preparing shared worker runtime..." >&2
  "$PYTHON_BIN" - \
    "$TMPDIR/worker.tgz" \
    "$TMPDIR/bundle-url" \
    "$STATE_DIR/install.lock" \
    "$RUNTIME_DIR" \
    "$RUNTIME_METADATA" \
    "$(cat "$TMPDIR/bundle-version")" \
    "$(cat "$TMPDIR/bundle-sha256")" \
    "$(cat "$TMPDIR/bundle-size")" <<'PY'
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO

(
    archive_path,
    bundle_url_path,
    lock_path,
    runtime_path,
    metadata_path,
    version,
    expected_digest,
    expected_size,
) = sys.argv[1:]
archive = Path(archive_path)
bundle_url = Path(bundle_url_path).read_text(encoding="utf-8")
lock_file = Path(lock_path)
runtime = Path(runtime_path)
metadata = Path(metadata_path)
expected_size_int = int(expected_size)
state_dir = runtime.parent
staging = state_dir / f"{expected_digest}.install.{uuid.uuid4().hex}"
backup = state_dir / f"{expected_digest}.previous.{uuid.uuid4().hex}"
required = (
    "local_shell_mcp/__init__.py",
    "local_shell_mcp/remote_worker/__init__.py",
    "local_shell_mcp/remote_worker/__main__.py",
    "local_shell_mcp/remote_worker/compat.py",
    "local_shell_mcp/remote_worker/identity.py",
    "local_shell_mcp/remote_worker/lifecycle.py",
    "local_shell_mcp/remote_worker/migration.py",
    "local_shell_mcp/remote_worker/profile_launcher.py",
    "local_shell_mcp/remote_worker/profiles.py",
    "local_shell_mcp/remote_worker/state.py",
    "local_shell_mcp/remote_worker/worker.py",
)
state_dir.mkdir(parents=True, exist_ok=True)
with contextlib.suppress(OSError):
    state_dir.chmod(0o700)
lock_file.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def install_lock(handle: BinaryIO) -> Generator[None]:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def runtime_is_complete() -> bool:
    try:
        decoded = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(decoded, dict)
        and decoded.get("schema_version") == 1
        and decoded.get("bundle_version") == version
        and decoded.get("sha256") == expected_digest
        and all((runtime / relative).is_file() for relative in required)
    )


def target_for(name: str) -> Path:
    pure = PurePosixPath(name.rstrip("/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise SystemExit(f"unsafe worker bundle path: {name}")
    target = staging.joinpath(*pure.parts)
    root = staging.resolve()
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"unsafe worker bundle path: {name}")
    return target


with lock_file.open("a+b") as lock_handle, install_lock(lock_handle):
    with contextlib.suppress(OSError):
        lock_file.chmod(0o600)
    if runtime_is_complete():
        print(
            f"Reusing worker runtime {version} ({expected_digest[:12]}).",
            file=sys.stderr,
        )
        raise SystemExit(0)

    print("Downloading worker bundle...", file=sys.stderr)
    completed = subprocess.run(
        [
            "curl",
            "-fSs",
            "-H",
            "Cache-Control: no-cache",
            "-H",
            "Pragma: no-cache",
            bundle_url,
            "-o",
            str(archive),
        ],
        check=False,
    )
    if completed.returncode:
        raise SystemExit("worker bundle download failed")
    payload = archive.read_bytes()
    if len(payload) != expected_size_int:
        raise SystemExit("worker bundle size does not match manifest")
    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise SystemExit("worker bundle checksum does not match manifest")

    seen = set()
    file_count = 0
    total_size = 0
    try:
        staging.mkdir()
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                name = member.name.rstrip("/")
                target = target_for(name)
                if name in seen:
                    raise SystemExit(
                        f"duplicate worker bundle path: {member.name}"
                    )
                seen.add(name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=False)
                    continue
                if not member.isreg():
                    raise SystemExit(
                        f"unsupported worker bundle member: {member.name}"
                    )
                file_count += 1
                total_size += member.size
                if file_count > 4096 or total_size > 128 * 1024 * 1024:
                    raise SystemExit(
                        "worker bundle extracted content exceeds limits"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise SystemExit(
                        f"duplicate worker bundle path: {member.name}"
                    )
                source = tar.extractfile(member)
                if source is None:
                    raise SystemExit(
                        f"worker bundle file is unreadable: {member.name}"
                    )
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                with contextlib.suppress(OSError):
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)

        for relative in required:
            if not (staging / relative).is_file():
                raise SystemExit(
                    f"worker bundle is incomplete: missing {relative}"
                )

        old_metadata = metadata.read_bytes() if metadata.exists() else None
        try:
            if runtime.exists():
                os.replace(runtime, backup)
            os.replace(staging, runtime)
            temporary_metadata = metadata.with_name(
                f"{metadata.name}.{uuid.uuid4().hex}.tmp"
            )
            temporary_metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "bundle_version": version,
                        "sha256": expected_digest,
                        "size": expected_size_int,
                        "installed_at": time.time(),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            with contextlib.suppress(OSError):
                temporary_metadata.chmod(0o600)
            os.replace(temporary_metadata, metadata)
        except BaseException:
            shutil.rmtree(runtime, ignore_errors=True)
            if backup.exists():
                os.replace(backup, runtime)
            if old_metadata is None:
                metadata.unlink(missing_ok=True)
            else:
                metadata.write_bytes(old_metadata)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
PY
}

worker_args() {
  ARGS=(connect --server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR" --profile "$PROFILE_ID")
  if [ -n "$NAME" ]; then ARGS+=(--name "$NAME"); fi
}

start_worker() {
  echo "Starting worker with $PYTHON_BIN..." >&2
  printf 'Worker profile: %s\nReconnect with:\n  %q %q\n' "$PROFILE_ID" "$LAUNCHER" "$PROFILE_ID" >&2
  export LOCAL_SHELL_MCP_WORKER_STATE_DIR="$STATE_DIR"
  export LOCAL_SHELL_MCP_WORKER_RUNTIME_SHA256="$RUNTIME_DIGEST"
  export PYTHONPATH="$RUNTIME_DIR${PYTHONPATH:+:$PYTHONPATH}"
  worker_args
  cd "$RUNTIME_DIR"
  if [ "$BACKGROUND" = "1" ]; then
    nohup "$PYTHON_BIN" -m local_shell_mcp.remote_worker "${ARGS[@]}" > "$PROFILE_DIR/worker.log" 2>&1 &
    echo "local-shell-mcp worker started in background. Log: $PROFILE_DIR/worker.log"
  else
    exec "$PYTHON_BIN" -m local_shell_mcp.remote_worker "${ARGS[@]}"
  fi
}

main() {
  parse_args "$@"
  require_basic_tools
  mkdir -p "$STATE_DIR"
  STATE_DIR="$(cd "$STATE_DIR" && pwd -P)"
  chmod 700 "$STATE_DIR" 2>/dev/null || true
  TMPDIR="$(mktemp -d "$STATE_DIR/install.XXXXXX")"
  trap cleanup EXIT
  find_or_install_python
  select_launcher_path
  prepare_profile
  download_manifest
  configure_runtime
  if runtime_is_installed; then
    echo "Reusing worker runtime $RUNTIME_VERSION (${RUNTIME_DIGEST:0:12})." >&2
  else
    install_bundle
  fi
  write_profile_metadata
  install_launcher
  start_worker
}

main "$@"
