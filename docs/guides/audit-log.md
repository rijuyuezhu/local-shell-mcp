# Audit log

The audit log is a short-term JSONL record of routed tool activity. It is intended for debugging, post-session review, and safety analysis in disposable or otherwise controlled environments.

## Location

By default, the audit log is stored at:

```text
/workspace/.local-shell-mcp/audit_log/audit.jsonl
```

The path is derived from `LOCAL_SHELL_MCP_STATE_DIR`; only the size limit is configurable:

```env
LOCAL_SHELL_MCP_STATE_DIR=/workspace/.local-shell-mcp
LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES=20000000
```

## Watch activity

In Docker Compose:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit_log/audit.jsonl
```

## Record shape

Every normal routed MCP or REST debug tool call produces a start/end pair linked by `call_id`:

```json
{"ts": 1710000000.0, "event": "tool_call_start", "call_id": "...", "transport": "mcp", "tool": "read_file", "input": {"path": "README.md"}, "principal": null, "context": {}}
{"ts": 1710000000.1, "event": "tool_call_end", "call_id": "...", "transport": "mcp", "tool": "read_file", "ok": true, "duration_ms": 12, "output": {"ok": true, "message": "", "data": {"path": "README.md", "content": "..."}}}
```

Failures and timeouts are also linked by `call_id`.

Other event families may appear alongside routed tool calls, including `run_start_persistent_shell`, `run_shell_command_end`, `start_persistent_shell`, `send_persistent_shell_input`, `read_persistent_shell_output`, `kill_persistent_shell`, `auth_ok`, `oauth_*`, `tool_error`, `tool_timeout`, and `remote_worker_registered`.

## Sensitive data warning

Audit records intentionally store complete tool inputs and outputs, including file contents, command output, authentication claims, and other sensitive values visible to the server. Treat the audit log as sensitive session state, not as sanitized telemetry.

Keep it in the configured state directory, rely on size limits for short-term retention, and avoid copying it to less trusted systems.
