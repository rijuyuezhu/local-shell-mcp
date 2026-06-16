# Upstream sync review: REST validation error normalization

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `f92e662`
- Decision: **Adapted as tests only.**

## Structure review

The upstream patch modified the old top-level `http_app.py`. Current main has `server/http/errors.py` and declarative HTTP handlers, so direct code porting would be a structural regression.

## Compatibility review

The existing `ValueError` and `HTTPException` handlers already produce the normalized envelope. The tests use `run_shell_command` and the current 60-second cap instead of upstream’s old route and timeout text.

## Tests and validation

Adds `tests/test_http_validation.py`; targeted local command: `uv run python -m pytest -q tests/test_http_validation.py`.
