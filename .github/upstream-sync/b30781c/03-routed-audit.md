# Upstream sync review: routed MCP tool-call audit

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `5f9682d`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

Current main centralizes routed call auditing in `tools/local_invocations.py` for REST and `server/mcp/watchdogs.py` for FastMCP, with shared helpers in `audit.py`. Upstream changed the old `tools.py` path, which is no longer canonical.

## Compatibility review

The current tests record input/output audit pairs for HTTP and MCP tool calls, including structured error paths. No behavior change is needed.

## Tests and validation

No code was changed. Existing coverage lives in `tests/test_audit_tool_calls.py` and CI will run it.
