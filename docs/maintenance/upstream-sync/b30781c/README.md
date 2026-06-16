# Selective upstream sync through 3382d10

This ledger records how the upstream range through `3382d10` was handled in the
selective merge commit `28a7e19`.

The merge commit uses upstream `3382d10` as its second parent. After this merge,
Git ancestry treats the upstream range through `3382d10` as merged, even though
some tree changes were intentionally skipped or deferred. Deferred items listed
here will not automatically reappear in a later ordinary upstream merge; they
need a dedicated future port, cherry-pick, or reimplementation.

Deferred or skipped categories in this sync include:

- docs-site/i18n rewrite
- Windows native session/ConPTY backend
- upstream 2.x release metadata, lint, and version-line changes

Ported categories include the remote worker startup/bootstrap fixes and the
locally adapted community/process file subset. Other categories are recorded as
already covered by the current architecture or adapted as tests.
