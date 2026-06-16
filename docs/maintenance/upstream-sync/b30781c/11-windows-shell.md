# Upstream sync review: Windows native sessions and ConPTY backend

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): `ea79fa9`, `4c838fe`
- Decision: **Skipped for this sync.**

## Structure review

Current main’s persistent shell abstraction is tmux-oriented and targets Python 3.14. Upstream adds a Windows backend through the old shell module structure, which does not map cleanly onto the current ops split.

## Compatibility review

A Windows backend may be valuable, but it needs a dedicated design with a backend interface, optional platform dependency handling, and CI coverage without weakening Linux/container behavior.

## Tests and validation

No code was changed. The feature remains a candidate for a dedicated future PR.
