#!/usr/bin/env bash
set -euo pipefail
SERVER=__REMOTE_SERVER__
BUNDLE_URL="$SERVER__REMOTE_WORKER_BUNDLE_PATH__"
INVITE=""
NAME=""
WORKDIR=""
BACKGROUND=0
PERSIST=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --invite) INVITE="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --workdir) WORKDIR="${2:-}"; shift 2 ;;
    --background) BACKGROUND=1; shift ;;
    --persist) PERSIST=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$INVITE" ]; then echo "--invite is required" >&2; exit 2; fi
if [ -z "$WORKDIR" ]; then WORKDIR="$PWD"; fi
if ! command -v python3 >/dev/null 2>&1; then echo "python3 is required" >&2; exit 2; fi
if ! command -v curl >/dev/null 2>&1; then echo "curl is required" >&2; exit 2; fi
if ! command -v tar >/dev/null 2>&1; then echo "tar is required" >&2; exit 2; fi
TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
curl -fsSL "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
tar -xzf "$TMPDIR/worker.tgz" -C "$TMPDIR"
export PYTHONPATH="$TMPDIR:$TMPDIR/vendor:${PYTHONPATH:-}"
ARGS=(--server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR")
if [ -n "$NAME" ]; then ARGS+=(--name "$NAME"); fi
if [ "$PERSIST" = "1" ]; then ARGS+=(--persist); fi
if [ "$BACKGROUND" = "1" ]; then
  mkdir -p "$HOME/.local/state/local-shell-mcp-worker"
  nohup python3 -m local_shell_mcp.main worker "${ARGS[@]}" > "$HOME/.local/state/local-shell-mcp-worker/worker.log" 2>&1 &
  echo "local-shell-mcp worker started in background. Log: $HOME/.local/state/local-shell-mcp-worker/worker.log"
else
  exec python3 -m local_shell_mcp.main worker "${ARGS[@]}"
fi
