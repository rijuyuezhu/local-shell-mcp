# Upstream sync review: MCP tool descriptions

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `2516bd2`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

Current main stores descriptions with registry functions and context-aware helpers in `tools/registry/*`. Upstream modified descriptions in the old `tools.py` module.

## Compatibility review

The current descriptions include defaults, limits, transport notes, and remote-worker guidance. The `relaxed_client_tool_hints` setting keeps client-specific metadata optional.

## Tests and validation

No code was changed. Existing surface assertions in `tests/test_tool_surface.py` and CI will cover regressions.
