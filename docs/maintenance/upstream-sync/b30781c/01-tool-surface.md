# Upstream sync review: stable MCP tool surface coverage

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `be33c71`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

The current tree uses the declarative registry plus `tests/test_tool_surface.py` to assert the local and remote MCP surface. Porting upstream `src/local_shell_mcp/tools.py` tests directly would reintroduce the old single-module surface and fight the current `tools/registry/*` layout.

## Compatibility review

No runtime behavior change. The local test also covers transport-specific hiding of remote HTTP routes and FastMCP validation behavior, which is stricter than the upstream patch shape.

## Tests and validation

No code was changed. CI should still run the full repository checks for this documentation-only review PR.
