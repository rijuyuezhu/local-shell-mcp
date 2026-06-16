# Upstream sync review: remote worker capability checks

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `60db561`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

Current main derives worker allowlists and proxy route definitions from `remote/tool_specs.py`; worker registration stores advertised capabilities and info in `remote/manager.py`.

## Compatibility review

Unsupported remote worker tools are rejected before execution, and remote environment info exposes the worker capability inventory. Directly porting upstream `remote.py` would undo the package split.

## Tests and validation

No code was changed. Existing coverage is in `tests/test_tool_surface.py` and `tests/test_e2e_remote_worker.py`.
