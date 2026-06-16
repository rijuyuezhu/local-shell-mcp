# Upstream sync review: metadata, lint-only, and release version commits

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `acfbbfc`, `1c81534`, `a3a6267`
- Decision: **Skipped or already superseded.**

## Structure review

Current main is on the `3.6.0` project line with Python 3.14 and its own lint/test layout. Upstream metadata and version commits belong to the upstream `2.x` line.

## Compatibility review

Applying upstream version metadata would downgrade the project. The upstream lint-only commit is not separately portable because its tests are adapted or skipped with corresponding feature PRs.

## Tests and validation

No code was changed. CI will validate that this documentation-only decision does not disturb the tree.
