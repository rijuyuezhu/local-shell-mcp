#!/usr/bin/env bash
set -euo pipefail

: "${TUNNEL_HOSTNAME:?Set TUNNEL_HOSTNAME, e.g. mcp.example.com}"
: "${LOCAL_SHELL_MCP_CF_ACCESS_TEAM_DOMAIN:?Set Cloudflare Access team domain}"
: "${LOCAL_SHELL_MCP_CF_ACCESS_AUDIENCE:?Set Cloudflare Access AUD tag}"

LOCAL_SHELL_MCP_MODE=mcp local-shell-mcp --mode mcp &
MCP_PID=$!
trap 'kill $MCP_PID || true' EXIT

cloudflared tunnel --url "http://127.0.0.1:${LOCAL_SHELL_MCP_PORT:-8765}" --hostname "$TUNNEL_HOSTNAME"
