#!/usr/bin/env bash
set -euo pipefail
BASE=${BASE:-http://127.0.0.1:8765}
curl -s "$BASE/healthz" | jq .
curl -s "$BASE/tools/run_shell" \
  -H 'content-type: application/json' \
  -d '{"command":"pwd && echo hello && ls -la","cwd":"."}' | jq .
