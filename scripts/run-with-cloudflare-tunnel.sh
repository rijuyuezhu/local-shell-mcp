#!/usr/bin/env bash
set -euo pipefail

set -a
source .env
set +a

LOCAL_SHELL_MCP_MODE=mcp uv run local-shell-mcp --mode mcp &
MCP_PID=$!
trap 'kill $MCP_PID || true' EXIT

cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN"
