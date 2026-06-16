# Upstream sync review: HTTP/MCP parity coverage

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `2a308c8`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

Current main derives HTTP handlers and MCP registration from `DeclarativeToolRegistry`, avoiding duplicated upstream-style route tables.

## Compatibility review

The existing parity tests compare selected REST and MCP payloads and check transport-specific remote route gating. No current code changes are required.

## Tests and validation

No code was changed. Existing coverage is in `tests/test_tool_surface.py` and e2e HTTP/MCP tests.
