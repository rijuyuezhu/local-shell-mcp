# Upstream sync ledger

This directory records selective upstream synchronization decisions.

Each subdirectory corresponds to an upstream synchronization point and captures
whether individual upstream changes were ported, adapted, skipped, or deferred.
These notes are maintenance records rather than GitHub platform configuration,
so they live outside `.github/`.

When a selective merge commit uses an upstream commit as a parent, Git ancestry
will treat the upstream range through that parent as merged even if some tree
changes were intentionally skipped. Deferred items in these notes therefore need
future manual porting, cherry-picking, or reimplementation; they should not be
expected to reappear automatically in a later ordinary upstream merge.
