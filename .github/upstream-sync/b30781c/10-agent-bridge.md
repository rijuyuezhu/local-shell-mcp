# Upstream sync review: agent bridge core modules

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `7d71773`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

Current main already has `agent_bridge/` split into models, registry, redaction, service, skills, state, and adapters, plus registry-facing tools. Upstream’s first-pass module set is older and less integrated with current boundaries.

## Compatibility review

The current bridge keeps config redaction and shared MCP/REST service behavior. Directly porting upstream files would risk regressing local refinements.

## Tests and validation

No code was changed. Existing coverage is in agent bridge tests.
