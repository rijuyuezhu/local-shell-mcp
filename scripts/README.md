# Repository automation

The `scripts` tree contains repository, CI, release, and development automation.
Scripts are grouped by the lifecycle they own rather than by implementation
language. Moving a script must update workflow, pre-commit, source-package,
provenance, test, and documentation references in the same change.

## `validation`

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `validation/check-coverage.py` | Reads Coverage.py JSON reports, writes cross-environment baselines, and enforces aggregate plus risk-weighted per-module coverage floors. It must run with the standard library alone before the project is installed. | Coverage is a repository quality gate rather than runtime or release behavior. Keeping the checker beside its policy data makes the zero-install validation boundary explicit. |
| `validation/coverage-baseline.json` | Stores aggregate minima, per-source observations, and the serialized risk classification consumed by the coverage checker. | The file is policy input for the checker, not generated package data or application configuration, so both validation artifacts move together. |

The remaining root-level scripts are transitional and will move in later,
independently validated phases. User-facing convenience launchers may remain at
stable root paths when their documented invocation is itself part of the public
workflow.
