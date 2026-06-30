#!/usr/bin/env bash
set -euo pipefail

SERVER=__REMOTE_SERVER__
BUNDLE_URL="$SERVER__REMOTE_WORKER_BUNDLE_PATH__"
INVITE=""
NAME=""
WORKDIR=""
BACKGROUND=0
PERSIST=0
TMPDIR=""
PYTHON_BIN=""
UV_BIN=""

usage() {
  cat >&2 <<'EOF'
usage: join_worker.sh --invite CODE [--name NAME] [--workdir PATH] [--background] [--persist]
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
      --background) BACKGROUND=1; shift ;;
      --persist) PERSIST=1; shift ;;
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
  have tar || die "tar is required"
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
  echo "uv not found; downloading a temporary uv into /tmp..." >&2
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

download_and_extract_bundle() {
  echo "Downloading worker bundle..." >&2
  curl -fL --progress-bar "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
  echo "Extracting worker bundle..." >&2
  tar -xzf "$TMPDIR/worker.tgz" -C "$TMPDIR"
}

worker_args() {
  ARGS=(--server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR")
  if [ -n "$NAME" ]; then ARGS+=(--name "$NAME"); fi
  if [ "$PERSIST" = "1" ]; then ARGS+=(--persist); fi
}

start_worker() {
  echo "Starting worker with $PYTHON_BIN..." >&2
  export PYTHONPATH="$TMPDIR:${PYTHONPATH:-}"
  worker_args
  if [ "$BACKGROUND" = "1" ]; then
    mkdir -p "$HOME/.local/state/local-shell-mcp-worker"
    nohup "$PYTHON_BIN" -m local_shell_mcp.remote_worker "${ARGS[@]}" > "$HOME/.local/state/local-shell-mcp-worker/worker.log" 2>&1 &
    echo "local-shell-mcp worker started in background. Log: $HOME/.local/state/local-shell-mcp-worker/worker.log"
  else
    exec "$PYTHON_BIN" -m local_shell_mcp.remote_worker "${ARGS[@]}"
  fi
}

main() {
  parse_args "$@"
  require_basic_tools
  TMPDIR="$(mktemp -d)"
  trap cleanup EXIT
  find_or_install_python
  download_and_extract_bundle
  start_worker
}

main "$@"
