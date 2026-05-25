#!/usr/bin/env bash
set -euo pipefail
export LOCAL_SHELL_MCP_AUTH_MODE=${LOCAL_SHELL_MCP_AUTH_MODE:-none}
export LOCAL_SHELL_MCP_MODE=mcp
exec local-shell-mcp --mode mcp
