# Upstream sync review: community files

- Upstream range: `4384da8..b30781c`
- Upstream commit(s): community subset of `9a284ea`
- Decision: **Ported with local text adaptation.**

## Structure review

This PR takes only small repository process files. It does not import upstream's broad docs or localization tree, which is reviewed separately.

## Compatibility review

Templates are adapted to the current fork, current Python 3.14 checks, and the existing architecture notes.

## Tests and validation

No runtime code changed. CI will run repository checks.
