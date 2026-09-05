#!/usr/bin/env bash
set -euo pipefail

set -a
source .env
set +a

uv sync
WORKGATE_MODE=mcp ./.venv/bin/python -m workgate.main server --mode mcp &
MCP_PID=$!
trap 'kill $MCP_PID || true' EXIT

cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN"
