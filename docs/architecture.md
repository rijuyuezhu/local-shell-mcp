# Architecture and module ownership

This page records the intended ownership of source packages and files. It is a
maintenance contract, not only a directory overview: when code moves, update the
ownership rationale and the architecture tests in the same change.

## Dependency direction

The target application structure separates process entry points, protocol
executors, shared HTTP infrastructure, Human UI behavior, transport-neutral
operations, and domain services:

```text
local_shell_mcp/
  main.py                 argparse root and command registration
  executors/
    mcp/                   MCP executor and MCP-only middleware
    http/                  REST/tool HTTP executor
  http/                    executor-neutral ASGI and HTTP infrastructure
  ui/
    ...                    transport-neutral Human UI core and runtimes
    http/                  Human UI HTTP adapters and routes
  tools/                   public tool contracts and registration
    ops/                   audited tool-owned operation implementations
    schemas/               audited tool-owned input and result contracts
  jobs/                    shared durable background-job domain
  ops/                     shared transport-neutral operations
  schemas/                 shared cross-domain contracts
  config/                  settings and configuration surface
  agent_bridge/            external agent capability domain
  remote/                  controller-side remote-worker domain
  remote_worker/           source-only worker runtime
  tool_session/            explicit local/remote workspace session state
  utils/                   small dependency-leaf technical primitives
```

The MCP and REST/tool HTTP executors live in their final `executors/mcp` and
`executors/http` packages. Human UI delivery adapters live in `ui/http`, and
executor-neutral ASGI infrastructure lives in `http`. The obsolete `server`
package has been removed and must not be restored.

The package root is frozen to `__init__.py`, `main.py`, `errors.py`, and
`version.py`. Every other implementation must live in an explicitly owned
subpackage; `tests/test_architecture.py` enforces this allowlist.

General rules:

- `main.py` owns only the root argparse parser and composes domain-owned CLI
  registration functions. Command modules load settings and invoke their own
  runtime handlers; `main.py` must not inspect `sys.argv` or import runtime apps.
- Executors may compose tools, OAuth, remote services, shared HTTP
  infrastructure, and UI route contributions.
- `http` must not import an executor or Human UI implementation.
- UI core must not import an executor. `ui/http` may depend on UI core and
  transport-neutral operations and domain services.
- `ops`, `tools`, `schemas`, domain packages, and worker code must not import
  executors or UI HTTP adapters. A module moves into `tools/{ops,schemas}` only
  after its complete consumer graph is tool-owned; shared UI, worker, remote,
  release, terminal, or infrastructure contracts remain in an explicit shared
  domain until separately extracted. Every remaining top-level `ops` family has
  completed this audit and is a deliberate shared owner, not migration backlog.
- `utils` is for small dependency-leaf technical primitives, not a holding area
  for domain algorithms or large workflows.

## CLI composition and registration

The command-line interface is one explicit argparse tree. `main.py` creates the
root parser, requires a public subcommand, invokes domain registration functions,
and dispatches the handler stored by argparse. It contains no command-specific
arguments, settings loading, runtime imports, or `argv[0]` special cases. The
private durable-job runner is also a normal argparse subcommand and is labeled
internal in help rather than parsed by a separate code path.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `main.py` | Creates the root parser, installs `--version`, calls each command registrar, parses once, and invokes the selected argparse handler. | The package entry point composes CLI contracts but does not own any command's arguments or runtime behavior. |
| `config/cli.py` | Registers config-file selection and generated Settings overrides, then loads and optionally installs settings from one parsed namespace. | Server, TUI, and Agent Bridge administration share this argparse/settings bridge without making `main.py` own configuration. |
| `executors/cli.py` | Registers the explicit `server` command, composes runtime services from resolved settings, and selects MCP, stdio, or REST execution. | Server process composition belongs beside the selectable protocol executors; lower layers retain compatibility accessors but no longer construct the server's process-wide stores implicitly. |
| `executors/runtime_services.py` | Constructs the process-wide filesystem state store and tool-session store from one resolved `Settings` object, then installs their compatibility accessors. | This is the server composition boundary where concrete stateful services and configuration dependencies are intentionally assembled rather than discovered deep in domain code. |
| `ui/cli.py` | Registers `tui`, its settings, and loopback API override, then launches the native UI runtime. | Native-client arguments and defaults belong to the UI domain rather than the process entry point. |
| `agent_bridge/cli.py` | Registers `mcp auth` and `mcp secret` administration and executes credential/OAuth workflows. | Agent Bridge owns both the nested command contract and its security-sensitive handlers. |
| `remote_worker/cli.py` | Registers the worker command tree and executes enrollment, foreground runtime, service, log, and update actions. | Worker lifecycle commands are an independent product surface and remain reusable by the source-only worker launcher. |
| `version.py` | Owns version discovery/formatting and registers the detailed `version` subcommand. | Version data is shared by HTTP, UI, worker, and tools; only its tiny CLI adapter is added here rather than creating a second version owner. |
| `jobs/cli.py` | Registers the internal `job-runner` parser and binds it to the durable runner handler. | The runner's arguments belong to the jobs domain. It is a normal labeled argparse command, and the file is excluded from source-only worker bundles because workers need `jobs/runtime.py`, not controller process composition. |

Runtime commands are explicit: `server`, `tui`, `mcp`, `worker`, `version`, and
the labeled internal `job-runner`. Running `local-shell-mcp` without a command is
an argparse error.
Global `--version` remains an argparse version action. Settings flags follow the
command that consumes them, for example `local-shell-mcp server --mode mcp` and
`local-shell-mcp tui --port 8765`.

Rejected alternatives:

- implicit server startup with no subcommand: it makes root options double as one
  command's contract and prevents a clear extensible command tree.
- inspecting `argv[0]` for `job-runner`: it bypasses argparse composition, help,
  validation, and module-owned registration.
- defining all parsers and handlers in `main.py`: it couples the entry point to
  every runtime and makes command ownership unclear.

## `executors/mcp`: MCP protocol executor

The `executors/mcp` package owns framework-specific MCP composition and runtime
policy. It converts transport-neutral tool registries and shared services into a
FastMCP server, then runs that server over stdio or wraps the MCP SDK's ASGI app
for HTTP delivery. The HTTP wrapper installs the same `ui/http` routes used by
the REST executor before the catch-all MCP mount. The browser shell and assets
remain public, while Human UI APIs retain OAuth or trusted-loopback TUI checks.

Allowed dependencies include tools, operations, OAuth adapters, remote route
contributions, the shared `ui/http/routes.py` route contract, executor-neutral
`http` infrastructure, audit recording, and MCP SDK types. Lower-level packages
must not import this executor. `executors/cli.py`
selects and invokes it after argparse dispatch; `main.py` imports only that registrar.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `executors/__init__.py` | Declares protocol executors as the application boundary that exposes local capabilities. | It names the layer without exporting a global executor registry or service locator. |
| `executors/mcp/__init__.py` | Declares the MCP executor and MCP-specific adapter boundary. | The marker separates protocol execution from transport-neutral tools and shared HTTP infrastructure. |
| `executors/mcp/app.py` | Registers tool registries with FastMCP, installs MCP policies, builds authenticated MCP-over-HTTP ASGI wrappers, and launches stdio or HTTP execution. | These decisions compose the MCP SDK and choose MCP runtime modes; they are executor behavior, not reusable HTTP infrastructure or tool business logic. |
| `executors/mcp/instructions.py` | Stores the exact server instructions advertised to MCP clients and exported to generated reference documentation. | The text is an MCP presentation contract. It is not a generic application prompt and should change only with MCP-facing workflow semantics. |
| `executors/mcp/session_limits.py` | Limits creation of stateful Streamable HTTP MCP sessions and audits capacity rejection. | The middleware understands MCP session IDs and SDK session-manager internals, so it is MCP-specific rather than general ASGI infrastructure. |
| `executors/mcp/transport_security.py` | Derives MCP SDK Host/Origin allowlists and DNS-rebinding protection from configured public URLs. | It adapts application settings to the MCP SDK's transport-security model; generic OAuth and HTTP security remain in their own packages. |
| `executors/mcp/watchdogs.py` | Wraps MCP tool functions with audit context, timeout enforcement, structured timeout behavior, and result/error recording. | The wrapper targets FastMCP tool objects and MCP error presentation while delegating timeout values and handler behavior to transport-neutral layers. |

Rejected ownership alternatives:

- `server/mcp`: “server” obscures that this is one selectable executor beside
  REST/tool HTTP execution and Human UI delivery.
- `http`: stdio execution, FastMCP registration, MCP sessions, and MCP tool
  wrappers are protocol-executor concerns, not shared HTTP infrastructure.
- `tools`: tool declarations are transport-neutral; FastMCP registration and
  MCP-specific presentation must depend on tools, not the reverse.

## `executors/http`: REST/tool HTTP executor

The `executors/http` package owns the FastAPI application that exposes local tool
registries as REST endpoints. It defines the REST error representation, applies
tool-route timeout and cache policy, records HTTP-routed tool invocations, and
composes public route contributions and authentication into one runnable app.

Allowed dependencies include tools, operations, OAuth adapters, remote route
contributions, executor-neutral `http` infrastructure, framework-specific
FastAPI/Starlette types, and the explicit `ui.http.routes.human_ui_routes`
composition contract. Lower-level packages must not import this executor.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `executors/http/__init__.py` | Declares the REST/tool HTTP executor boundary. | It distinguishes FastAPI execution from shared HTTP infrastructure and Human UI route ownership. |
| `executors/http/app.py` | Builds and runs the authenticated FastAPI application, composes public and feature-gated routes, registers REST tools, installs limits and error policy, and consumes the Human UI route contribution. | It is the application-composition root for this executor; shared route factories stay in their owning domains and UI behavior remains outside the executor. |
| `executors/http/errors.py` | Installs the REST JSON error envelope and maps validation, operating-system, unknown-tool, HTTP, and unexpected exceptions to public responses. | The response schema and status mapping are REST executor presentation policy, not generic exception utilities. |
| `executors/http/invocations.py` | Invokes transport-neutral local tool handlers from REST routes while recording HTTP transport audit start/end events and serializing audit output. | It is the REST transport boundary around tool execution; the actual handler and result conversion remain reusable lower-layer services. |
| `executors/http/tool_routes.py` | Registers tool definitions as FastAPI `GET`/`POST` routes and installs REST-specific timeout and no-store middleware. | Route methods, URL interpretation, HTTP timeouts, and response cache headers are executor behavior rather than tool definitions or shared ASGI infrastructure. |

Rejected ownership alternatives:

- `server/http`: “server” conflates executable REST composition with Human UI
  delivery and shared HTTP infrastructure.
- top-level `http`: generic request limits, health, and download response
  mechanics are shared; REST tool registration and error envelopes are not.
- `tools`: REST route generation consumes transport-neutral tool registries;
  putting it in `tools` would make the domain layer own a specific executor.
- `ui/http`: the executor consumes UI route contributions, but it also runs
  correctly without Human UI and owns all non-UI REST tool behavior.

## `http`: executor-neutral HTTP infrastructure

The `http` package contains ASGI and HTTP behavior needed by more than one
executor. It does not decide which executor runs and does not own REST tools,
MCP protocol behavior, OAuth business rules, remote-worker business logic, or
Human UI workflows.

Allowed dependencies include configuration contracts, audit recording,
transport-neutral operations, version reporting, and Starlette ASGI types.
The package must not import `executors` or UI modules, and no removed `server`
namespace may be reintroduced as an intermediary.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `http/__init__.py` | Declares the package as executor-neutral ASGI/HTTP infrastructure. | The package marker documents the boundary without exporting an application service locator. |
| `http/health.py` | Builds `/healthz`, `/readyz`, and `/version` Starlette routes and their responses. | These endpoints are HTTP infrastructure shared by REST and MCP-over-HTTP, not behavior of either executor. |
| `http/downloads.py` | Adapts claimed tokenized download snapshots into bounded HTTP `GET`/`HEAD` responses, safe content-disposition headers, streaming cleanup, and audit events. | Download claiming remains in `ops`; this file owns only the HTTP representation and lifecycle of a public download response. It therefore does not belong in generic utilities or a specific executor. |
| `http/public_routes.py` | Composes the public non-OAuth health and download route set shared by HTTP-capable executors. | It is a small route contribution contract consumed by executors. OAuth and feature-specific remote routes remain owned by their domains and are composed at the executor/application layer. |

`tests/test_http_route_parity.py` locks the shared `/healthz`, `/readyz`,
`/version`, and `/download/{token}` route signatures, order, installation, and
public-matcher classification across both REST and MCP-over-HTTP executors.
| `http/request_limits.py` | Implements and installs the shared ASGI request-body size limit, including streaming-transfer exemptions and rejection auditing. | The middleware applies to REST, MCP-over-HTTP, OAuth, and remote routes. It is ASGI infrastructure rather than REST or MCP protocol behavior. |

Rejected ownership alternatives:

- `server/shared`: the name ties reusable HTTP infrastructure to an overloaded
  server package and hides that the code is protocol-executor neutral.
- `utils`: these modules expose concrete Starlette/ASGI contracts and HTTP
  semantics; they are not general-purpose technical helpers.
- `executors/http` or `executors/mcp`: both executors consume the behavior, so
  either location would reverse the other executor's dependency direction.


## `ops`: shared transport-neutral operations

The `ops` package is the shared application-operation layer. These modules back
public tools, but they also serve source-only workers, Human UI adapters, generic
HTTP routes, remote transfer services, the job runtime, or other operation
families. Consequently, importing them from `tools` would reverse dependency
direction: shared runtimes would depend on the public tool-registration layer.
The current consumer graph has been fully audited; `ops` is no longer a staging
area for unaudited moves.

| File | Responsibility | Why it remains shared |
| --- | --- | --- |
| `ops/__init__.py` | Declares the shared operation namespace. | The package is consumed across tools, workers, UI, HTTP, remote services, and domain runtimes. |
| `ops/agent.py` | Lists, activates, reads, and invokes Agent Bridge capabilities. | Both the public agent registry and source-only worker dispatch execute these operations. |
| `ops/bash.py` | Composes session-aware bounded commands, durable jobs, persistent shells, remote dispatch, and temporary Python scripts into the public `bash`/`run_python_code` execution facade. | Keeping orchestration above the shell primitives lets the jobs runtime depend on the shell backend without creating a reverse `ops.shell` → `jobs.runtime` dependency. |
| `ops/downloads.py` | Creates, lists, revokes, claims, and releases tokenized immutable file downloads. | The public download tools and executor-neutral HTTP download route share the same state and claim policy. |
| `ops/files.py` | Implements contained, bounded workspace file listing, writing, editing, hashing, deletion, and link-safe path behavior. | Worker dispatch, Human UI files, remote transfer, read/search/secret-scan operations, and tool registries all reuse it. |
| `ops/image.py` | Loads bounded local or remote image bytes and projects native MCP image results. | The image tool and Human UI audit image preview share staging and validation behavior. |
| `ops/patch/__init__.py` | Dispatches session-bound unified diff and apply-patch operations locally or remotely. | The patch tool, worker dispatch, and shell patch-envelope mode consume the same operation. |
| `ops/patch/envelope.py` | Parses patch envelopes, applies deterministic hunks, and renders portable Git diffs. | It is a dependency of the shared patch operation and shell execution path, not a registry-only adapter. |
| `ops/read.py` | Resolves read selectors and projects files or directories into bounded model-facing output. | Both the read tool and source-only worker dispatch execute it. |
| `ops/remote.py` | Adapts remote-manager service actions into typed remote administration and tool-call outputs. | Its operation consumer is the remote registry, but its result contract is shared by `remote/{manager,service,transfer}`; moving only the operation would violate the complete-family rule, while moving the family would invert remote-domain dependencies. |
| `ops/search.py` | Implements bounded grep, glob, and directory-tree operations with local/remote session routing. | Worker dispatch, workspace connector orchestration, and public search tools share it. |
| `ops/secret_scan.py` | Scans bounded workspace text for credential-like patterns with Git-ignore and remote-session behavior. | Both the public scanner and source-only worker dispatch execute it. |
| `ops/session.py` | Creates, changes, and ends explicit sessions, collects environment/Git state, and starts session-copy jobs. | Both public session tools and source-only worker dispatch require the same lifecycle behavior. |
| `ops/shell.py` | Runs bounded shell-command primitives and owns persistent shell lifecycle operations. | The session-aware bash facade, worker terminal dispatch, Human UI terminals, HTTP/MCP watchdog integration, remote tools, and the shared job runtime depend on it without making the shell backend depend on durable jobs. |
| `ops/todo.py` | Persists revisioned, bounded agent todo lists. | Public todo tools, Human UI todos, and source-only worker dispatch share the state contract. |
| `ops/transfer.py` | Provides binary-safe transactional file and directory transfer primitives. | Controller/worker transfer services, transfer gateway, image staging, session copy, download snapshots, and public transfer tools all reuse it. |
| `ops/utils/__init__.py` | Declares operation-private shared helpers. | The helpers support multiple operation families without becoming general project utilities. |
| `ops/utils/bounded_runner.py` | Runs one bounded POSIX command as a Linux child subreaper and removes descendants before returning. | `ops/shell.py` invokes it through a lightweight private module/CLI entry point so ordinary bounded commands cannot leak background processes. |
| `ops/utils/download_snapshot.py` | Creates and reads immutable private snapshots for tokenized downloads. | Download HTTP/tool policy and transfer primitives jointly consume the snapshot lifecycle. |
| `ops/utils/download_store.py` | Persists and locks private tokenized-download metadata and claims. | The download operation and HTTP route share one durable claim store. |
| `ops/utils/path.py` | Resolves workspace-contained paths, bounded text input, scratch files, and cleanup. | File, patch, shell, transfer, terminal, and other shared operations reuse these safety primitives. |
| `ops/utils/remote_session.py` | Routes explicit sessions to remote workers and normalizes remote errors/results. | Many shared operations require the same controller-side dispatch seam; workers replace it through their compatibility layer. |
| `ops/utils/session_copy.py` | Coordinates local/local, local/remote, and remote/remote session-copy workflows as managed jobs. | Session operations, transfer gateway, shared job runtime, and worker transfer primitives meet at this workflow. |
| `ops/utils/temp_file.py` | Creates validated managed temporary text files for operation workflows. | Patch and shell operations share it, while its policy remains operation-specific. |

Rejected ownership alternatives:

- moving the complete `ops/` tree under `tools/ops`: this would make workers,
  UI/HTTP adapters, remote services, and the job runtime depend on public tool
  ownership and would require bundling controller-only `tools` code on workers.
- treating top-level `ops` as unfinished migration: the current family graph is
  explicitly locked by architecture tests; a future move requires first removing
  every non-tool consumer or extracting a truthful shared domain.
- moving only `ops/remote.py`: its shared result contracts keep the remote family
  cross-domain, and partial family migration would weaken the registry/operation/
  schema alignment contract.

## `jobs`: shared durable background-job domain

The `jobs` package owns durable tracked-job state and execution that must work
independently of public tool registration. It is included in the source-only
worker bundle and may depend on shell operations, session state, configuration,
audit recording, private-file primitives, and shared job result contracts. It
must not import `tools`, executors, UI adapters, or controller-only remote
orchestration.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `jobs/__init__.py` | Declares the shared tracked-job domain boundary. | Job persistence and execution are used by the controller process, standalone runner, shell/session-copy workflows, and source-only workers, so they are broader than one public tool adapter. |
| `jobs/runtime.py` | Retains the stable jobs compatibility surface, lifecycle admission, mixed managed/shell listing and tailing, and public companion dispatch. | Existing callers and source-only workers keep one jobs API while backend-specific start/stop/retry execution is delegated below this facade. |
| `jobs/lifecycle.py` | Owns shell attempt materialization, durable status-file interpretation, bounded log reads, and shell/managed row reconciliation with managed liveness injected as callbacks. | The status state machine is shared by shell and managed operations; callback injection keeps it below both execution kinds instead of creating a managed↔shell dependency cycle. |
| `jobs/shell.py` | Owns shell-backed job start, live-shell reconciliation, stop, and retry transitions. | Persistent-shell inventory and lifecycle side effects now have one backend owner that depends on `ops.shell` without importing the managed backend. |
| `jobs/managed.py` | Owns managed-job handler registration, process-local task and lease state, durable progress/finish updates, and managed start/stop/retry/list lifecycle. | Managed execution now has one authoritative owner while `jobs/runtime.py` only preserves compatibility aliases and coordinates mixed shell/managed public operations. |
| `jobs/persistence.py` | Owns the durable job-store schema, primary/backup load-save recovery, attempt artifact paths, and retention pruning. | These filesystem and schema responsibilities form a dependency leaf below recovery and both job execution kinds; they preserve the existing JSON format and fail-closed backup behavior. |
| `jobs/recovery.py` | Owns bounded cross-process job-store transactions plus the managed deferred-update journal and replay rules. | Locking and crash recovery must share one authoritative state machine while depending only on persistence and row semantics, not on managed or shell lifecycle orchestration. |
| `jobs/state.py` | Owns common row identity, operation tokens, public `JobInfo` projection, and bounded managed JSON normalization. | Recovery, managed jobs, and shell-backed jobs all depend on these row semantics, so they form a small dependency leaf instead of importing each other or `runtime.py`. |
| `jobs/runner.py` | Executes one standalone durable shell attempt, bounds its log, and atomically writes the terminal status payload. | The child-process runner has a narrow process/IO contract and does not need the store, session lifecycle, or public job orchestration. |
| `jobs/cli.py` | Registers the private durable runner arguments as a labeled internal argparse subcommand and dispatches directly to `jobs/runner.py`. | Parser ownership follows the jobs domain; the source-only worker manifest includes the jobs modules imported by `jobs/runtime.py` so worker execution remains self-contained. |

Rejected ownership alternatives:

- `ops/jobs.py`: the old module mixed shared persistence/runner behavior with the
  public controller-side job companion, preventing a truthful single owner for
  the `job` tool family.
- `tools/ops/jobs.py`: only controller-side local/remote result orchestration
  belongs there; moving the runtime would force source-only workers and process
  entrypoints to depend on the tool-registration layer.
- `utils`: job state, lifecycle, and recovery form a cohesive domain rather than
  small dependency-leaf helpers.

## `tools`: public contracts and tool-owned implementations

The `tools` package owns public tool registration, metadata, and implementation
slices whose complete production consumer graph is tool-specific. The current
migration audit is complete: top-level `ops` and `schemas` are deliberate shared
owners, while each accepted tool-only slice moves operation and schema contracts
together without compatibility wrappers.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `tools/ops/__init__.py` | Declares the namespace for audited tool-owned operation implementations. | It distinguishes tool business logic from shared domain capabilities and from registry adapters. |
| `tools/ops/audit.py` | Resolves explicit local/remote sessions, queries audit listings or details, maps remote session identifiers, excludes the active local call, and returns typed audit results. | Only the audit tool registry consumes this orchestration. Audit persistence, session state, and remote dispatch remain shared domains below the tool-owned operation. |
| `tools/ops/jobs.py` | Validates the unified job companion action, merges controller-managed and remote-worker job snapshots, routes poll/cancel/retry identifiers to the correct owner, preserves caller order, and degrades remote list failures when controller jobs remain available. | This local/remote projection is consumed only by the public job registry. Durable state, local actions, managed handlers, and runner behavior remain in the shared `jobs` domain. |
| `tools/ops/version.py` | Converts package/runtime version metadata into the typed version-tool result. | Its only production consumer is the version tool registry, so keeping it at top-level `ops` implied reuse that does not exist. |
| `tools/ops/workspace_connector.py` | Implements connector-compatible workspace search/fetch projection, bounded result-card deduplication, stable error envelopes, and auditing while delegating file reads and grep search to shared operations. | Only the workspace connector registry consumes this orchestration. Its dependencies remain shared capabilities; placing the adapter in top-level `ops` advertised broader reuse than its actual consumer graph. |
| `tools/schemas/__init__.py` | Declares the namespace for tool-owned input and result contracts. | It keeps tool-only schemas with their public tool surface while shared contracts remain at top-level `schemas`. |
| `tools/schemas/input_models/__init__.py` | Declares tool-owned input contracts. | The marker establishes the final package shape for migrated tool families. |
| `tools/schemas/input_models/audit.py` | Defines bounded audit filters, timestamps, sort order, detail id, and full-payload annotations. | These annotations describe only the public audit tool input surface; shared session-id input remains in the shared schema package. |
| `tools/schemas/input_models/jobs.py` | Defines list, poll, cancel, retry, include-finished, and bounded-tail annotations for the unified job companion. | These annotations describe only the public job tool input surface; shared job lifecycle result models remain at top-level `schemas` because runtime, session, transfer, and worker code consume them. |
| `tools/schemas/input_models/version.py` | Documents the intentionally argument-free version tool input contract. | The contract exists only to keep the version tool's operation/registry/schema slice structurally complete. |
| `tools/schemas/input_models/workspace_connector.py` | Defines annotated literal-search and fetch-id arguments for connector clients. | These annotations describe only the public workspace connector tools and have no shared domain consumer. |
| `tools/schemas/result_models/__init__.py` | Declares tool-owned structured result contracts. | It separates public tool response schemas from shared cross-domain result models. |
| `tools/schemas/result_models/audit.py` | Defines the session-scoped audit listing/detail output contract and entry metadata. | Only the audit operation and registry consume this response model; raw audit records remain owned by the audit domain. |
| `tools/schemas/result_models/version.py` | Defines `VersionInfoOutput` for package, distribution, Python, and platform metadata. | Only the version operation and registry consume it; no UI, worker, remote, executor, release, or infrastructure module depends on it. |
| `tools/schemas/result_models/workspace_connector.py` | Defines connector search cards, result collections, and fetched-document payloads. | The models are consumed only by the workspace connector operation and registry, so they belong with that tool-owned slice rather than shared schemas. |

Rejected ownership alternatives:

- top-level `ops/{audit,jobs,version,workspace_connector}.py` and corresponding
  `schemas/**` files: their placement advertised transport-neutral reuse despite
  exclusively tool-owned consumer graphs.
- matching `tools/registry/*.py`: registration adapts operations to declarative
  tool metadata; combining implementation and schemas into registry adapters
  would erase the operation/contract boundary.
- source-only worker bundle: workers execute shared job runtime actions but do
  not import controller-side public-tool orchestration, so migrated `tools/` files
  must not be included incidentally by operation or schema wildcards.

## `tool_session`: explicit workspace-session state

The `tool_session` package owns durable local/remote agent-session metadata,
grounding snapshots, session admission, resource ownership, and retention policy.
Filesystem layout and atomic storage mechanics remain below it in `persistence`.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `tool_session/store.py` | Retains the stable `ToolSessionStore` API and coordinates session admission, lifecycle leases, pruning revalidation, resource transactions, and snapshot transactions. | Callers keep one authoritative session surface while metadata, retention, resource, and snapshot mechanics are delegated without duplicating lifecycle invariants. |
| `tool_session/repository.py` | Owns session-metadata paths, process-local metadata cache, durable load/list/write/remove mechanics, and root-change cache reset. | Repository mechanics change independently from expiry policy and lifecycle orchestration while `ToolSessionStore` preserves compatibility wrappers for existing callers and race tests. |
| `tool_session/records.py` | Defines durable `AgentSession`/`SnapshotRecord` records, opaque-id helpers, payload validation, compatibility decoding, and exact snapshot JSON sizing. | Durable formats are dependency-leaf contracts shared by repositories and policy code; they must not depend on store orchestration. |
| `tool_session/resources.py` | Owns pure persistent-shell ownership validation and immutable session-record transitions for bind, reserve, release, and reconciliation. | Resource policy becomes independently testable while locks, durable transactions, authoritative reloads, and session admission remain in `ToolSessionStore`. |
| `tool_session/retention.py` | Interprets durable job state into conservative session-protection sets and owns pure expiry/capacity eligibility policy. | Job liveness and retention rules can evolve independently while `ToolSessionStore` retains lifecycle leases, jobs-lock revalidation, and deletion orchestration. |
| `tool_session/snapshots.py` | Owns per-session grounding-snapshot cache, loading, retention, and persistence below an already-admitted session transaction. | Snapshot storage policy can change independently while session existence, lifecycle locking, and transaction admission remain authoritative in `ToolSessionStore`. |
| `tool_session/lifecycle.py` | Provides keyed in-process and cross-process session lifecycle leases. | Admission ordering and lifecycle serialization are shared concurrency primitives below the session store and job/shell callers. |
| `tool_session/environment.py` / `selectors.py` | Normalize session environment bindings and semantic session selectors. | These are narrow session-domain helpers independent of persistence orchestration. |

## `persistence`: shared private-state layout and file-store primitives

The `persistence` package owns the canonical directory layout below the configured
state root and the small filesystem primitives shared by durable repositories. It
does not own domain schemas, retention policy, migrations, or application-level
state transitions. Session metadata, snapshots, Todo, session-local Audit, jobs,
OAuth, downloads, remote workers, and UI modules retain their own validation and
lifecycle rules while resolving paths through this package.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `persistence/__init__.py` | Exposes the shared state layout, storage protocol, filesystem implementation, and configured store accessor. | Consumers need one narrow import boundary without depending on implementation internals. |
| `persistence/store.py` | Defines canonical state paths, including colocated session metadata, snapshots, Todo, and Audit files; validates path components and root containment; creates owner-private directories; performs bounded JSON reads and atomic private writes; removes state paths; enumerates session directories; and provides keyed thread/process transactions. | These are storage mechanics shared across domains. Domain payload formats, compatibility policy, retention, and recovery decisions remain with their owners. |

Rejected ownership alternatives:

- `utils`: the layout and store define a stateful cross-domain contract rather
  than a small stateless helper.
- `config`: configuration selects the state root, but it must not own filesystem
  mutation, locking, serialization, or domain directory structure.
- one repository per domain with independently constructed paths: that recreates
  the inconsistent storage layout and permissions this boundary is intended to
  eliminate.
- compatibility or migration logic in the shared store: old layouts are not read
  or migrated; each current repository uses only the canonical layout.

## `telemetry`: transport-neutral host and process observations

The `telemetry` package collects best-effort runtime observations without
choosing how they are displayed. It may depend on configuration and operating
system APIs, but it must not import UI projections, protocol executors, HTTP
adapters, audit presentation, or remote-controller services.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `telemetry/__init__.py` | Declares the transport-neutral telemetry capability boundary. | It gives host observations explicit ownership instead of hiding them in a Dashboard-named module or generic utilities. |
| `telemetry/system.py` | Samples process uptime and host CPU, memory, disk, load, and network metrics with portable fallbacks and bounded values. | The observations can support UI, diagnostics, or future health policy. They contain no Dashboard labels, audit projection, route handling, or executor logic. |

Rejected ownership alternatives:

- `ui/dashboard.py`: sampling is useful independently of a particular view model
  and should not force non-UI consumers to depend on Dashboard semantics.
- `utils`: sampling owns process-wide state and a coherent telemetry contract;
  it is not a small stateless helper.
- `ops`: collecting observations is a capability, not a user-triggered tool use
  case or command workflow.

## `ui`: transport-neutral Human UI core

The `ui` package owns Human UI view models, native-client runtime contracts, and
UI-specific security behavior. UI core must not import protocol executors or
HTTP route adapters. Controller and source-only worker adapters may invoke UI
core capabilities when serving a Human UI, but those capabilities remain
internal rather than public tools.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `ui/__init__.py` | Declares the Human UI core boundary independently of HTTP delivery. | It prevents UI behavior from appearing to be part of the REST executor and allows browser and native clients to share core contracts. |
| `ui/cli.py` | Registers the explicit native TUI command, shared settings overrides, loopback API default, and runtime handler. | The root CLI composes this registrar without importing UI runtime behavior directly. |
| `ui/contracts.py` | Defines the stable POSIX and Windows OpenTUI executable filenames and resolves the current-platform name. | Runtime discovery, source-only session probes, release wheel construction, and generated Bun build inputs need one dependency-leaf naming contract without importing each other. |
| `ui/dashboard.py` | Combines neutral system telemetry with metadata-only audit summaries, alerts, activity rows, health state, and version data for local or remote Dashboard clients. | The output is a Dashboard view model with UI labels and disclosure policy. Remote-worker support only transports this internal UI capability; it does not make the projection a generic telemetry or public tool contract. |
| `ui/image_preview.py` | Decodes validated image bytes into bounded, orientation-corrected RGBA thumbnails and terminal-cell dimensions for native UI rendering. | The output is a UI view model tied to terminal rendering constraints. It contains no HTTP request parsing or response construction, so browser/HTTP adapters consume it rather than own it. |
| `ui/runtime.py` | Resolves configured or trusted OpenTUI executables, finds source-mode entrypoints, materializes bounded embedded payloads into private state, validates loopback API bases, and launches the native client with credentials confined to its environment. | These operations are the native Human UI runtime boundary. Release tooling creates the payload and HTTP adapters may request a launch, but neither owns client discovery, extraction, or execution policy. |
| `ui/security.py` | Owns the Human UI API namespace, private loopback-client credential lifecycle, constant-time token verification, and direct-peer loopback classification. | These rules define the Human UI trust boundary used by OAuth middleware, browser/native adapters, and the native launcher. They are UI policy rather than general OAuth, HTTP, or filesystem helpers. |
| `ui/session.py` | Defines purpose-isolated Human UI session tokens, a separately derived signing key, canonical browser origins, origin-bound audiences and cookie names, browser-binding digests, and transport-neutral CSRF verification. | Browser sessions inherit approved OAuth scopes without becoming MCP bearer credentials; the signed cookie is unusable outside the exact browser request origin or without its companion token, while HTTP request-origin derivation, cookie parsing, and response mutation remain in `ui/http/session.py`. |

Rejected ownership alternatives:

- top-level `dashboard.py`: the name exposes no package boundary and previously
  mixed generic host sampling with UI projection.
- `telemetry`: audit activity labels, alerts, health presentation, and redaction
  choices are view-model policy rather than raw observations.
- `server/http`: the same Dashboard projection is used locally and through a
  source-only worker before any HTTP response is built. Image decoding likewise
  belongs below the HTTP adapter because it is independent of query parameters
  and JSON response construction.
- top-level `image_preview.py`: a package-root file hid that thumbnail generation
  is a Human UI rendering capability rather than a project-wide utility.
- top-level `ui_security.py`: the old location obscured that the local-token
  bypass is narrowly scoped Human UI policy, not a general authentication or
  transport-security facility.
- top-level `tui_runtime.py`: package-root placement hid that executable
  discovery, embedded-payload extraction, and process launch are one native UI
  runtime contract.
- `release`: release code builds and embeds the sidecar, but runtime resolution
  and extraction policy belongs to the client that consumes it.
- duplicated runtime/release literals: executable names are a cross-layer artifact
  contract, so `ui/contracts.py` owns them and the Bun-side mirror is generated and
  checked rather than maintained as an independent source of truth.
- `oauth`: OAuth middleware consumes the UI trust decision, but credential
  creation and loopback UI namespace rules must remain owned by the UI domain.

### `ui/static`: packaged browser assets

The `ui/static` directory owns the immutable HTML, CSS, JavaScript, third-party
license, syntax-highlighting, and terminal-rendering assets served by
`ui/http/routes.py`. Keeping the assets under the UI domain makes their product
ownership explicit while preserving their package-data role; they contain no
Python modules and are deliberately excluded from the source-only remote-worker
runtime.

The directory contains exactly the browser shell (`index.html`), Human UI styles
(`web.css`), the classic bootstrap controller (`web.js`), feature ES modules such
as `dashboard.js` and `remotes.js`, the OpenTUI console bridge, syntax highlighter,
terminal renderer, vendored xterm bundle and stylesheet, and the corresponding
license notice. Build and architecture gates reject symlinks, Python files,
unexpected assets, and restoration of the former top-level `ui_static` path.

The browser controller presents agent state through one Sessions control surface:
machine and recent/all session selection precede session details, Todo, and the
session-local Audit view. The separate Global Audit panel deliberately retains
machine-wide lifecycle, control-plane, and other events that are not owned by one
session. The browser never exposes worker-internal session identifiers.

Rejected ownership alternatives:

- top-level `ui_static`: the name exposed package mechanics without expressing
  that these files belong exclusively to the Human UI product surface.
- `ui/http/static`: HTTP adapters serve the files, but the same assets are UI
  product resources packaged independently of any specific executor.
- `executors/http`: the REST executor composes routes and middleware; it must not
  own browser presentation resources.

### `ui/http`: Human UI delivery adapters

The `ui/http` package owns Starlette request parsing, authorization checks,
response normalization, route composition, and WebSocket delivery for the Human
UI. It may consume transport-neutral UI core and domain capabilities, but it must
not depend on either protocol executor. The REST executor consumes only
`ui.http.routes.human_ui_routes` during application composition; no intermediate
`server` namespace remains.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `ui/http/__init__.py` | Declares the browser/native Human UI HTTP and WebSocket adapter boundary. | It separates delivery-specific code from transport-neutral UI view models, security, and native runtime behavior. |
| `ui/http/routes.py` | Serves the packaged browser shell and traversal-safe static assets, builds bootstrap and machine inventory responses, and composes the complete/public Human UI route sets. | This is the single route contribution consumed by the REST executor; it owns UI delivery composition rather than executor assembly. |
| `ui/http/session.py` | Resolves the browser-visible origin from the request `Host`, the configured origin when its canonical authority matches, and otherwise the direct transport or same-authority browser `Origin`; exchanges approved PKCE codes or explicitly supplied OAuth bearers into persistent HttpOnly Human UI cookies bound to that origin and an origin-scoped companion token; applies double-submit CSRF and resolved-origin checks; clears browser sessions; and adapts the binding for HTTP headers and WebSocket subprotocols. | Standard OAuth bearer issuance and configured issuer/resource identity remain in `oauth`; the authority-constrained configured-scheme fallback supports TLS termination without trusting forwarded headers, direct loopback can still use an external issuer, JavaScript never persists bearers, and host-scoped cookies remain insufficient for replay from a sibling scheme or port. |
| `ui/http/common.py` | Provides shared JSON error envelopes, bounded text/integer validation, stable file-entry sorting, and remote-machine lookup for UI adapters. | These helpers encode Human UI HTTP response and input conventions used by several routes, not project-wide utility behavior. |
| `ui/http/audit.py` | Parses global versus session-local audit query/detail scopes, maps public remote sessions to worker bindings, dispatches local or remote reads, normalizes bounded summaries/details, and projects payload or image metadata into UI responses. | Dual audit persistence remains in `audit`; this module owns only its authenticated Human UI HTTP representation. |
| `ui/http/dashboard.py` | Authorizes and dispatches local/remote Dashboard snapshots and normalizes system, version, alert, activity, and health values into stable JSON. | The transport-neutral Dashboard projection lives in `ui/dashboard.py`; this file owns request and response adaptation. |
| `ui/http/session_snapshot.py` | Combines one session's Todo state with bounded Audit summaries and one selected preview, using one worker RPC for remote sessions. | Session metadata remains controller-owned, Todo persistence remains in `ops.todo`, and Audit persistence remains in `audit`; this adapter only coordinates an authenticated UI snapshot. |
| `ui/http/files.py` | Implements local workspace list, preview, content, write, mkdir, delete, copy, move, and rename HTTP actions while delegating remote requests to the remote-file adapter. | Filesystem operations and remote RPC stay in their domains; this module owns Human UI file semantics, scope checks, and response envelopes. |
| `ui/http/image_preview.py` | Validates preview dimensions and converts core RGBA preview results into JSON-safe terminal-image fields. | Core decoding belongs in `ui/image_preview.py`; query/body normalization and response fields are HTTP adapter concerns. |
| `ui/http/opentui.py` | Wraps Unix and Windows OpenTUI child processes and bridges one authenticated native-console WebSocket with bounded idle and cleanup behavior. | Native executable discovery remains in `ui/runtime.py`; this module owns WebSocket/process delivery for an HTTP-hosted UI session. |
| `ui/http/remote_files.py` | Normalizes remote UI paths, caches bounded worker sessions, dispatches workspace RPCs, reads/decodes chunks, and implements remote preview/content/mutation payloads. | It is the Human UI adapter over remote-worker workspace tools, not the worker control plane or generic remote manager. |
| `ui/http/remotes.py` | Presents worker inventory and validates invite, rename, and revoke HTTP actions with scope and mutation-policy checks. | Remote lifecycle remains in `remote`; this file owns the Human UI administration representation. |
| `ui/http/sessions.py` | Lists durable public agent/workspace sessions for one local or remote machine, defaults inventory to sessions active in the prior five hours, exposes an explicit all-sessions toggle, and persists the irreversible immediate-termination control action while hiding worker-internal bindings. | Session lifecycle, activity timestamps, and termination policy remain in `tool_session`; this adapter owns authenticated Human UI inventory, machine-scoped projection, and control-plane authorization. |
| `ui/http/terminals.py` | Adapts local/remote persistent-shell list/start/send/read/resize/kill operations and raw terminal bridges to REST and WebSocket protocols with bounded validation and cleanup. | Terminal backends and bridge capabilities remain in `terminal`; this large module owns their Human UI delivery contract and is a later split candidate. |
| `ui/http/todos.py` | Maps the centrally selected authenticated local or remote UI session to revisioned Todo reads/writes and stable JSON responses. | Todo state belongs inside tool-session storage; this module owns its Human UI HTTP semantics and remote dispatch, not an independent global Todo surface. |

Rejected ownership alternatives:

- `server/http`: that path mixed one product surface with a generic “server”
  namespace and obscured the separation between MCP and REST executors.
- `executors/http`: the executor assembles middleware and route contributions;
  it should not own Human UI feature adapters or static assets.
- transport-neutral `ui` core modules: Starlette requests, responses, scopes, and
  WebSockets are delivery details and must not leak into reusable UI contracts.
- `utils`: validation and normalization here implement the Human UI HTTP schema,
  not generally reusable primitives.

## `terminal`: interactive terminal backends and lifecycle

The `terminal` package owns terminal-emulation backends and the bounded lifecycle
operations needed by local tools, source-only workers, and Human UI adapters. It
may depend on configuration, audit, schemas, and low-level operation helpers, but
it must not depend on protocol executors, HTTP route adapters, or UI presentation.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `terminal/__init__.py` | Declares the cross-platform interactive-terminal capability boundary. | It gives ConPTY, raw attachment, and tmux helper code one explicit domain rather than leaving platform implementations at package root. |
| `terminal/bridge.py` | Owns opaque raw-attachment capabilities, exclusive per-shell bridge leases, bounded base64 stream reads/writes, resize/close behavior, idle expiry, POSIX tmux-attach PTYs, and Windows ConPTY subscriptions. | This lifecycle is shared by local tools, remote-worker RPC adapters, and Human UI HTTP/WebSocket adapters before transport-specific normalization. It belongs with terminal backends rather than UI or worker dispatch. |
| `terminal/contracts.py` | Defines the shared minimum and maximum rows/columns accepted by persistent shells, raw bridges, and terminal UI adapters. | The limits constrain the terminal domain itself. Keeping them below `ops.shell` prevents backends and adapters from depending on a high-level operation module while preserving `ops.shell` compatibility re-exports. |
| `terminal/conpty.py` | Implements Windows ConPTY availability, process spawning, persistent-shell state, bounded reads/writes/resizes, raw attachment handles, cleanup, and startup-error classification. | This is a terminal backend consumed by shell operations and the raw terminal bridge. It is not a generic Windows utility, UI route, or executor concern. |
| `terminal/tmux.py` | Resolves configured or system tmux executables, selects the pinned Linux bundled helper from the package root, validates regular/executable helper files, reports backend diagnostics, and raises actionable persistent-shell errors. | tmux selection is a terminal-backend capability shared by shell operations, raw attachments, tool-session probes, source-only workers, and frozen Linux releases. Release workflows build the helper, but runtime selection belongs to the terminal domain. |

Rejected ownership alternatives:

- top-level `conpty.py`, `terminal_bridge.py`, and `tmux_helper.py`: package-root
  placement exposed implementation details without identifying the interactive-
  terminal capability they serve.
- `utils`: ConPTY and bridge registries own stateful process, capability, and
  stream lifecycles rather than reusable stateless helpers.
- `ops/shell.py`: shell operations select and orchestrate terminal backends; they
  should not own backend implementations or shared terminal-dimension contracts.
- `ui/http`: Human UI adapters consume raw bridges, but the same lifecycle is
  also used by local tools and source-only remote workers before HTTP delivery.

## `audit`: redacted event persistence and query

The `audit` package owns the transport-neutral lifecycle of bounded, redacted
audit events. Every session-owned event is appended to both the global log and
that session's colocated log; events without a session remain global-only. The
global log remains authoritative for payload-object retention, while local logs
provide direct per-session reads without re-scanning unrelated records. Audit may
consume configuration, persistence primitives, tool-session identity, redaction,
and the current payload store, but it must not depend on protocol executors, HTTP
route adapters, Human UI presentation, or terminal implementations.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `audit/__init__.py` | Preserves the stable `local_shell_mcp.audit` import contract, explicitly exports supported operations, and forwards legacy read-only diagnostic attributes to the implementation. | Callers should depend on one audit-domain facade rather than the physical location of a large implementation module. |
| `audit/core.py` | Sanitizes arbitrary values, redacts credentials and download capabilities, binds public session identities to tool-call context, bounds and encodes events, appends global and session-local JSONL records, enforces rotation and global payload retention, externalizes payloads, coalesces tool-call records, and serves bounded global or per-session query/detail views. | These responsibilities form one transport-neutral audit-event lifecycle shared by MCP, REST, Human UI, jobs, workers, OAuth, downloads, and shell operations. |
| `audit/payloads.py` | Canonically encodes sanitized values, stores oversized content as private content-addressed gzip objects, validates no-follow regular files, resolves bounded references, and prunes expired or unreferenced payloads. | Payload objects are an internal persistence extension of audit events. Their digest, retention, integrity, and disclosure rules belong beside the event store rather than at package root or in generic file utilities. |

Rejected ownership alternatives:

- top-level `audit.py` and `audit_payloads.py`: they split one audit persistence
  domain across unrelated package-root files and made implementation paths look
  like supported public APIs.
- `utils`: audit policy includes redaction, retention, event semantics, payload
  references, and public query behavior rather than generic serialization.
- `executors` or `ui/http`: those layers emit and present audit events, but the
  same event store is shared across every delivery surface.

## Patch operation ownership

Patch application is split into orchestration and domain mechanics inside `ops`:

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `ops/patch/__init__.py` | Resolves local or remote sessions, bounds patch input, materializes temporary files, runs `git apply --check` and apply phases with timeouts, audits execution, and returns typed results. | This is an application operation coordinating sessions, subprocesses, remote dispatch, audit, and result models. |
| `ops/patch/envelope.py` | Parses apply-patch envelopes, validates cwd-contained paths and UTF-8 targets, applies deterministic hunks, preserves newline and executable-mode semantics, and renders portable unified diffs. | These mechanics implement the patch operation's domain syntax and safety rules. They are not generic utilities and have no transport or session ownership. |

Rejected ownership alternatives:

- top-level `patch_ops.py`: package-root placement obscured that the parser exists
  solely to support the apply-patch operation.
- `utils`: envelope grammar, hunk matching, cwd containment, and Git diff
  rendering are cohesive patch-domain policy rather than generally reusable
  helpers.

## Agent Bridge data and status boundaries

Agent Bridge configuration and discovery follow a one-way data dependency graph.
`models.py` is the pure contract leaf; auth, Skill scanning, and source discovery
consume those contracts. Public status projection sits above those domains so
models never import credential or presentation behavior.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `agent_bridge/models.py` | Defines validated manifest models and immutable registry records, including the ordered `SkillSource` path contract. | Auth, Skill parsing, source discovery, registry construction, and public adapters all share these shapes. The module must remain free of project-local imports. |
| `agent_bridge/sources.py` | Enumerates project, managed, and global Skill roots, re-exports the shared `SkillSource` type, and merges bounded scans in priority order. | It owns discovery policy and scan orchestration, while source data itself remains in the model leaf. |
| `agent_bridge/status.py` | Projects an `AgentCapabilityRegistry` into the redacted public configuration status, including auth state and sanitized probe errors. | Credential lookup and redaction are presentation concerns; moving them above models prevents the model layer from importing auth and recreating a cycle. |

Rejected ownership alternatives:

- `AgentCapabilityRegistry.config_status()`: placing auth-aware redaction on the
  data object forced `models.py` to import `auth.py`, reversing the intended
  dependency direction.
- defining `SkillSource` in `sources.py`: model and fingerprint annotations then
  had to point back into discovery policy.
- `utils`: these contracts and projections are specific to the Agent Bridge
  product surface rather than generic serialization helpers.

## `remote_worker/state.py`: worker process path contract

The source-only worker keeps persistent installation paths separate from bundle
installation and process-lock policy. Dependency direction is intentionally
one-way: `remote_worker/lifecycle.py` and `remote_worker/runtime.py` consume the
state contract; runtime may request lifecycle lock handoff during re-exec, but
lifecycle must not import runtime.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `remote_worker/state.py` | Resolves the configured, XDG, or home-relative worker state root and derives the runtime directory, metadata file, and single-instance lock file. | These paths are shared by installation and process lifecycle code, use only stdlib/environment state, and form a dependency leaf suitable for the source-only worker bundle. |

Rejected ownership alternatives:

- `remote_worker/runtime.py`: owning shared paths there forced lifecycle locking
  to depend on bundle installation and created a cycle when runtime requested a
  lock-preserving re-exec.
- `remote_worker/lifecycle.py`: runtime installation, service generation, and
  capability probes also consume the same persistent root.
- general `utils`: the environment names and derived layout are a worker product
  contract rather than a reusable filesystem primitive.

## `release`: artifact construction and verification

The `release` package owns build-time artifact assembly and validation. It is
outside runtime execution paths and must not depend on executors, HTTP adapters,
terminal runtime state, remote workers, or tool operations. Its only project-local
dependency is the dependency-leaf OpenTUI filename contract in `ui/contracts.py`.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `release/__init__.py` | Declares the release/build infrastructure boundary. | It distinguishes artifact construction code from runtime package APIs and leaves room for future release-only helpers without returning them to package root. |
| `release/platform_wheel.py` | Maps platform tags to native targets, verifies host and executable formats, compiles or stages OpenTUI payloads, rewrites deterministic wheels and metadata, regenerates RECORD, inspects wheels/sdists, serializes concurrent builds, and exposes the platform-wheel CLI. | These operations create and validate distributable artifacts; they are not runtime UI, terminal, packaging utility, or executor behavior. |

Rejected ownership alternatives:

- top-level `platform_wheel.py`: package-root placement made release tooling look
  like a runtime capability.
- `ui` or `terminal`: those packages consume the native assets at runtime, while
  release code constructs and proves the distributable payloads.
- `utils`: wheel metadata, binary format validation, deterministic archives, and
  release locking form one build-time domain rather than general helpers.

## Large-module reassessment

The post-migration ownership review compared the remaining large stateful
modules by responsibility clusters, dependency direction, monkeypatch surface,
source-only worker constraints, and existing test ownership. Only the jobs split
was accepted in this review:

- `jobs/runtime.py` and `tools/ops/jobs.py` now separate shared durable execution
  from the controller-only public-tool projection. The split removes the
  misleading `ops/jobs.py` owner while preserving the explicit
  `jobs.runtime <-> ops.shell` cycle as visible architecture debt.
- `ui/http/terminals.py` remains intact. Its HTTP validation, remote terminal
  normalization, raw bridge lifecycle, connection limits, authentication, and
  WebSocket orchestration share one protocol state machine and one concentrated
  test/monkeypatch surface. A future split requires a dedicated protocol
  contract and adapter-parity tests rather than a line-count-driven move.
- `remote/transfer_gateway.py` remains intact. Its ticket store, spool identity,
  authorization, range handling, cleanup, and router composition jointly enforce
  the transfer security and TOCTOU model. Separating them without a narrower
  security contract would increase risk and is not justified by the current
  consumer graph.

No further large-module decomposition is authorized by this review. Future
changes must begin from a concrete behavior, dependency, or testability problem
and complete their own focused commit, push, and exact-head CI closure.
