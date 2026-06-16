# Upstream sync review: shell subprocess environment filtering

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `5d01c5d`
- Decision: **Already covered locally; record as adapted/no code port.**

## Structure review

Current main implements shell environment filtering in `ops/command_ops.py`, not upstream’s old `shell_ops.py`. It blocks server configuration prefixes and selected runtime variables before spawning user commands.

## Compatibility review

The current policy is intentionally fixed for now, matching the local safety posture and avoiding extra configuration surface. Directly adding upstream settings would broaden behavior without a current need.

## Tests and validation

No code was changed. Existing coverage is in `tests/test_shell_ops.py`.
