# Runtime architecture migration guardrails

This document records the Phase 0 baseline and ownership rules for
[issue #112](https://github.com/rijuyuezhu/local-shell-mcp/issues/112). The
baseline is `21e9bbeb` (`refactor: harden architecture boundaries`, PR #111).
It is a migration document: stable conclusions should be folded into
`docs/architecture.md` as the migration closes rather than turning this file
into a second permanent architecture manual.

## Process composition contract

There are two primary long-lived service runtimes that need the shared domain
graph:

1. the controller/server runtime, which hosts MCP/HTTP/UI and the remote control
   plane; and
2. the source-only remote worker runtime, which hosts worker-local execution
   under the existing lazy-import and bundle constraints.

Other entrypoints are leaf processes. The native TUI, Agent Bridge
administration commands, `job-runner`, bounded-runner, and similar commands
should compose only the dependencies they actually use. They must not be
forced through a controller or worker runtime merely for architectural
symmetry.

A future `ControllerRuntime` or `WorkerRuntime` is an owner and composition
object, not an application-wide service locator. Runtime objects may retain
constructed services so they can start and close them deterministically, but
domain code must receive narrow services, config values, stores, or callables
directly. Passing a generic runtime/`ctx` object into business functions and
pulling arbitrary dependencies from it is outside the target architecture.

Controller and worker may share dependency-leaf contracts, immutable config
values, typed session bindings, and pure domain logic. Controller-only runtime
objects must not leak into the source-only worker.

Phase 4 materializes those two owners from the Search experiment. Shared store
construction is side-effect free; `ControllerRuntime` and `WorkerRuntime`
install the remaining compatibility accessors only while their async lifespan
is active and restore the prior bindings on close. The runtime object stays in
the composition/host layer: Search remains bound to its explicit store,
resolver, runner/client, and grounding capabilities rather than receiving a
runtime context.

## Directional dependency baseline

The Phase 0 architecture test treats these numbers as ceilings, not goals.
Usage may shrink without updating the baseline; growth fails the guardrail and
requires an explicit architectural justification.

| Signal | Calls / matches | Files |
| --- | ---: | ---: |
| `get_settings(` | 122 | 52 |
| `get_tool_session_store(` | 82 | 25 |
| `get_state_store(` | 29 | 15 |
| direct `session.target ==/!= "remote"` branches | 43 | 18 |

The remote-branch metric is intentionally a narrow directional proxy. Pairwise
routing such as Transfer/`session_copy` may legitimately retain domain-specific
route matrices; the metric is not a mandate to drive every branch to zero.

## Mutable process-state classification

Module-level state is not automatically a problem. Use these classifications
when deciding whether a global belongs in a runtime/domain owner:

- **immutable constant / regex / capability set** — keep module-level;
- **process identity** — keep module-level when intentionally one-per-process;
- **pure bounded cache or synchronization primitive** — may remain module-level
  when reset/close semantics are harmless and wrapping it would add ceremony;
- **lifecycle-owned mutable service/state** — move only when an owner can also
  define construction context, admission stop, drain/cancel behavior,
  reconciliation/flush where required, and idempotent close.

Moving a dictionary or singleton into a dataclass without defining those
lifecycle semantics does not satisfy the migration.

### Current lifecycle inventory

| Current state | Classification / intended owner | Migration note |
| --- | --- | --- |
| `remote/manager.py` / `REMOTE_MANAGER` | controller lifecycle-owned remote service | Move with pending remote calls/worker control-plane state in the non-Jobs lifecycle phase. |
| `terminal/bridge.py` / `_BRIDGES`, `_SHELL_BRIDGES`, `_PENDING_SHELLS` | terminal lifecycle-owned live bridge state | Bridges own timers/process attachments; the eventual owner must close them deterministically and make shutdown idempotent. |
| `jobs/managed.py` / `_MANAGED_JOB_TASKS`, `_MANAGED_JOB_LEASES` | Jobs-owned live state | Deliberately defer to the Jobs functional-core phase so ownership and reconciliation are redesigned once, not moved through a temporary generic runtime holder. |
| `jobs/managed.py` / `_MANAGED_JOB_HANDLERS` | process registration metadata pending Jobs review | Do not move merely to reduce a global-count metric; Phase 7 may make registration composition-scoped if that materially improves ownership/testing. |
| `ui/http/remote_files.py` / `_SESSION_CACHE` | controller/UI lifecycle-owned remote-file session state | Worker session bindings have external identity; the eventual owner must define invalidation/release behavior. The fixed lock shards can remain implementation detail unless ownership gives a concrete benefit. |
| `oauth/core/models.py` / `_CODES` plus `oauth/core/service.py` / `_AUTH_CODE_LOCK` | controller OAuth transient state | Authorization codes are short-lived process state and belong to an explicit OAuth owner when this area is migrated. |
| `oauth/core/models.py` / `_CLIENTS` plus `oauth/core/service.py` / `_OAUTH_CLIENT_LOCK` | controller OAuth client state | Preserve persistence semantics for approved clients while making process-local ownership explicit; do not conflate durable client data with transient authorization codes. |

The inventory is about ownership, not immediate movement. Jobs live maps are
explicitly excluded from the earlier global-migration phase; immutable
constants, process identity, and harmless bounded caches are not migration
success metrics.

## Lifecycle rule

For each lifecycle-owned resource that is migrated, the implementation PR must
answer all of the following before the old global is removed:

1. Which process/domain owns it?
2. On which event loop or execution context is it constructed?
3. How does shutdown stop admission of new work?
4. Which tasks, subprocesses, futures, queues, bridges, or leases are drained or
   cancelled, and in what order?
5. Which durable state must be reconciled or flushed before close completes?
6. Is repeated close safe?
7. Do startup failure, runtime exception, cancellation, and normal transport
   shutdown all reach the same cleanup contract?

For the controller, that lifecycle contract must work under MCP stdio,
MCP-over-HTTP, and REST HTTP. It must not rely on an ASGI-only fallback or a
stdio-only process global.
