# Upstream sync review: MCP tool export script

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `19fe715`
- Decision: **Adapted as tests only.**

## Structure review

Current main already has `scripts/export-tools-json.py` implemented against `server.mcp.app.build_mcp`. The upstream script targeted the older module layout, so no script rewrite is necessary.

## Compatibility review

The new test runs the script as an executable subprocess with dynamic agent and remote surfaces disabled, then validates the wrapped JSON shape and representative tool names.

## Tests and validation

Adds `tests/test_export_tools_json.py`; targeted local command: `uv run python -m pytest -q tests/test_export_tools_json.py`.
