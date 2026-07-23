# Audit log

The audit log is a short-term JSONL record of routed tool activity. It is intended for debugging, post-session review, and safety analysis in disposable or otherwise controlled environments.

## Location

By default, the audit log is stored at:

```text
/workspace/.local-shell-mcp/audit_log/audit.jsonl
```

The path is derived from `LOCAL_SHELL_MCP_STATE_DIR`. Recoverable sanitized payload objects are stored beside it under `audit_log/payloads/`. The log, event, payload, and retention budgets are configurable:

```env
LOCAL_SHELL_MCP_STATE_DIR=/workspace/.local-shell-mcp
LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES=20000000
LOCAL_SHELL_MCP_MAX_AUDIT_EVENT_BYTES=1000000
LOCAL_SHELL_MCP_AUDIT_PAYLOADS_ENABLED=true
LOCAL_SHELL_MCP_AUDIT_INLINE_VALUE_BYTES=16384
LOCAL_SHELL_MCP_MAX_AUDIT_PAYLOAD_BYTES=67108864
LOCAL_SHELL_MCP_MAX_AUDIT_PAYLOAD_STORE_BYTES=268435456
LOCAL_SHELL_MCP_AUDIT_PAYLOAD_RETENTION_S=604800
```

Append, payload publication, and retention are serialized across threads and processes. When either JSONL or referenced-payload quota is exceeded, recent retention units are atomically preserved; completed `tool_call_start`/`tool_call_end` pairs sharing a `call_id` are kept together. Unreferenced payloads are removed after the configured grace period, while expired references remain readable as explicit `expired` metadata. Set payload retention to `0` when no full recovery should be available.

## Watch activity

In Docker Compose:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit_log/audit.jsonl
```

## Record shape

Every normal routed MCP or REST debug tool call produces a start/end pair linked by `call_id`:

```json
{"ts": 1710000000.0, "event": "tool_call_start", "call_id": "...", "transport": "mcp", "tool": "read", "input": {"session_id": "Ab12Cd34", "path": "README.md:1-2"}, "principal": null, "context": {}}
{"ts": 1710000000.1, "event": "tool_call_end", "call_id": "...", "transport": "mcp", "tool": "read", "ok": true, "duration_ms": 12, "output": {"kind": "file", "path": "README.md", "content": "[README.md#snap1]\n1:# Project\n2:Intro", "numbered_content": "[README.md#snap1]\n1:# Project\n2:Intro", "file": {"path": "README.md", "bytes": 123, "bytes_read": 123, "total_lines": 2, "start_line": 1, "end_line": 2, "line_count": 2}, "session_id": "Ab12Cd34", "snapshot_id": "snap1", "seen_ranges": [{"start": 1, "end": 2}], "truncated": false}}
```

Failures and timeouts are also linked by `call_id`. Every event has a unique `id`. Each field is normalized and redacted before storage. Values larger than `audit_inline_value_bytes` are written as deterministic gzip-compressed canonical JSON addressed by SHA-256, and the JSONL field becomes a `$local_shell_mcp_audit_payload` reference containing version, digest, canonical byte count, creation time, and bounded preview. Values above `max_audit_payload_bytes` become explicit `$local_shell_mcp_audit_truncated` omission records. If the remaining event still exceeds `max_audit_event_bytes`, identity fields are retained and other fields are reduced to previews. Binary values are represented by byte count and SHA-256 rather than raw bytes.

Other event families may appear alongside routed tool calls, including `bash`, `job`, `send_persistent_shell_input`, `read_persistent_shell_output`, `kill_persistent_shell`, `auth_ok`, `oauth_*`, `tool_error`, `tool_timeout`, and `remote_worker_registered`.


## Query through MCP

Start an explicit local or remote session, then use `audit_tail(session_id=...)` instead of reading JSONL directly. The default list is coalesced, bounded, metadata-searchable, and returns payload references/previews only. Filters include event, operation, audit-session id, search text, timestamp range, sort order, and limit. The tool hides only its own currently executing lifecycle record, so earlier `audit_tail` calls remain available.

`audit:read` is required for listing and preview/detail references. To recover one retained sanitized value, pass its stable `entry_id` with `include_full_payloads=true`; this additionally requires `audit:full`. Full mode is intentionally unavailable for an unbounded list. Remote sessions dispatch the same query/detail operations to the paired worker and preserve worker-side machine/session isolation.

Every full read verifies the private object is a regular non-symlink file, enforces compressed and decompressed limits, checks the canonical JSON byte count and SHA-256 digest, and parses UTF-8 JSON. A missing, corrupt, or expired object is returned as an unresolved reference with a stable status instead of exposing filesystem diagnostics. Full recovery is byte-for-byte recovery of the retained sanitized JSON value, not recovery of credentials removed during redaction.

## Sensitive data warning

Within the per-event budget, the audit log preserves non-sensitive tool inputs, outputs, nested failures, file contents, and command output. Credential-like mapping keys, command-line flags, bearer tokens, configured OAuth approval PIN values, and tokenized download URLs are redacted on a best-effort basis. Irreversible identifiers such as `token_sha256` remain available for correlation.

Best-effort redaction is not a proof that a log contains no secrets: unknown secret formats and sensitive application data may remain. Treat the audit log as sensitive session state, not as sanitized telemetry. Keep it in the configured state directory, rely on size limits for short-term retention, and avoid copying it to less trusted systems.
