# Upstream sync review: worker dependency bootstrap

- Upstream range: `4384da8..3382d10`
- Upstream commit(s): `3382d10`
- Decision: **Ported with local-architecture adaptation.**

## Structure review

Upstream reduces remote worker startup dependencies in the old flat module layout. Current main already has a dedicated package entrypoint from the prior worker startup PR, but `remote/worker.py` still imported HTTP and tool-registry dependencies at module import time.

This PR keeps the current `remote/` package layout and makes the worker startup path standard-library only until a real tool job needs the local tool registry.

## Compatibility review

The worker polling loop now uses `urllib.request` and JSON from the standard library instead of `httpx`. The canonical local tool registry remains the execution path for jobs, but it is imported lazily by `execute_worker_tool` rather than during worker process startup.

The upstream `2.6.2` version bump and old settings/model fallback layout are not copied because the origin line is Python 3.14 and has a split settings/model architecture.

## Tests and validation

Adds `tests/test_remote_worker_bootstrap.py` to assert the worker entrypoint can import while common server-side dependencies are blocked, and keeps the existing remote-worker e2e test for the polling loop.
