# Upstream sync review: documentation site, Pages workflow, and i18n expansion

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `e1ee6cf`, `2c9e262`, `caa11f8`, `5f59004`, `9a284ea`, `65cfec4`, `112e027`, `9ceac6b`, `e49a142`
- Decision: **Mostly skipped; community templates handled separately.**

## Structure review

Current main already has a MkDocs site, docs workflow, and current navigation. Upstream’s large localized docs set is generated around a different information architecture and would add thousands of lines plus many nav conflicts.

## Compatibility review

The sync keeps the current English docs as canonical and does not introduce native MkDocs i18n until there is an explicit maintenance plan for translated pages.

## Tests and validation

No docs-site code was changed in this PR. CI will still run general checks.
