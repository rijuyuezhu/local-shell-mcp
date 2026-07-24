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
  main.py                 process composition and CLI dispatch
  executors/
    mcp/                   MCP executor and MCP-only middleware
    http/                  REST/tool HTTP executor
  http/                    executor-neutral ASGI and HTTP infrastructure
  ui/
    ...                    transport-neutral Human UI core and runtimes
    http/                  Human UI HTTP adapters and routes
  tools/                   public tool contracts and registration
  ops/                     transport-neutral use cases
  schemas/                 input and result contracts
  config/                  settings and configuration surface
  agent_bridge/            external agent capability domain
  remote/                  controller-side remote-worker domain
  remote_worker/           source-only worker runtime
  tool_session/            explicit local/remote workspace session state
  utils/                   small dependency-leaf technical primitives
```

The MCP and REST/tool HTTP executors now live in their final `executors/mcp` and
`executors/http` packages. `server/http` is now only a transitional Human UI HTTP
adapter location until the UI package move completes. New domain code must not
depend on the transitional package.

General rules:

- `main.py` may select and launch executors and native UI clients.
- Executors may compose tools, OAuth, remote services, shared HTTP
  infrastructure, and UI route contributions.
- `http` must not import an executor or Human UI implementation.
- UI core must not import an executor. `ui/http` may depend on UI core and
  transport-neutral operations and domain services.
- `ops`, `tools`, `schemas`, domain packages, and worker code must not import
  executors or UI HTTP adapters.
- `utils` is for small dependency-leaf technical primitives, not a holding area
  for domain algorithms or large workflows.

## `executors/mcp`: MCP protocol executor

The `executors/mcp` package owns framework-specific MCP composition and runtime
policy. It converts transport-neutral tool registries and shared services into a
FastMCP server, then runs that server over stdio or wraps the MCP SDK's ASGI app
for HTTP delivery.

Allowed dependencies include tools, operations, OAuth adapters, remote route
contributions, executor-neutral `http` infrastructure, audit recording, and MCP
SDK types. Lower-level packages must not import this executor. The process entry
point is the only production module outside `executors` that imports it.

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
contributions, executor-neutral `http` infrastructure, and framework-specific
FastAPI/Starlette types. The app currently imports one transitional Human UI
route contribution from `server/http/human_ui.py`; that exact dependency is
temporary and will move to `ui/http` in the UI phase. Lower-level packages must
not import this executor.

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
The package must not import `executors`, transitional `server` executor modules,
or UI modules.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `http/__init__.py` | Declares the package as executor-neutral ASGI/HTTP infrastructure. | The package marker documents the boundary without exporting an application service locator. |
| `http/health.py` | Builds `/healthz`, `/readyz`, and `/version` Starlette routes and their responses. | These endpoints are HTTP infrastructure shared by REST and MCP-over-HTTP, not behavior of either executor. |
| `http/downloads.py` | Adapts claimed tokenized download snapshots into bounded HTTP `GET`/`HEAD` responses, safe content-disposition headers, streaming cleanup, and audit events. | Download claiming remains in `ops`; this file owns only the HTTP representation and lifecycle of a public download response. It therefore does not belong in generic utilities or a specific executor. |
| `http/public_routes.py` | Composes the public non-OAuth health and download route set shared by HTTP-capable executors. | It is a small route contribution contract consumed by executors. OAuth and feature-specific remote routes remain owned by their domains and are composed at the executor/application layer. |
| `http/request_limits.py` | Implements and installs the shared ASGI request-body size limit, including streaming-transfer exemptions and rejection auditing. | The middleware applies to REST, MCP-over-HTTP, OAuth, and remote routes. It is ASGI infrastructure rather than REST or MCP protocol behavior. |

Rejected ownership alternatives:

- `server/shared`: the name ties reusable HTTP infrastructure to an overloaded
  server package and hides that the code is protocol-executor neutral.
- `utils`: these modules expose concrete Starlette/ASGI contracts and HTTP
  semantics; they are not general-purpose technical helpers.
- `executors/http` or `executors/mcp`: both executors consume the behavior, so
  either location would reverse the other executor's dependency direction.


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
| `ui/dashboard.py` | Combines neutral system telemetry with metadata-only audit summaries, alerts, activity rows, health state, and version data for local or remote Dashboard clients. | The output is a Dashboard view model with UI labels and disclosure policy. Remote-worker support only transports this internal UI capability; it does not make the projection a generic telemetry or public tool contract. |
| `ui/image_preview.py` | Decodes validated image bytes into bounded, orientation-corrected RGBA thumbnails and terminal-cell dimensions for native UI rendering. | The output is a UI view model tied to terminal rendering constraints. It contains no HTTP request parsing or response construction, so browser/HTTP adapters consume it rather than own it. |
| `ui/runtime.py` | Resolves configured or trusted OpenTUI executables, finds source-mode entrypoints, materializes bounded embedded payloads into private state, validates loopback API bases, and launches the native client with credentials confined to its environment. | These operations are the native Human UI runtime boundary. Release tooling creates the payload and HTTP adapters may request a launch, but neither owns client discovery, extraction, or execution policy. |
| `ui/security.py` | Owns the Human UI API namespace, private loopback-client credential lifecycle, constant-time token verification, and direct-peer loopback classification. | These rules define the Human UI trust boundary used by OAuth middleware, browser/native adapters, and the native launcher. They are UI policy rather than general OAuth, HTTP, or filesystem helpers. |

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
- `oauth`: OAuth middleware consumes the UI trust decision, but credential
  creation and loopback UI namespace rules must remain owned by the UI domain.

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
audit events. It may consume configuration, private-file primitives, redaction,
and the current payload store, but it must not depend on protocol executors, HTTP
route adapters, Human UI presentation, or terminal implementations.

| File | Responsibility | Why it belongs here |
| --- | --- | --- |
| `audit/__init__.py` | Preserves the stable `local_shell_mcp.audit` import contract, explicitly exports supported operations, and forwards legacy read-only diagnostic attributes to the implementation. | Callers should depend on one audit-domain facade rather than the physical location of a large implementation module. |
| `audit/core.py` | Sanitizes arbitrary values, redacts credentials and download capabilities, bounds and encodes events, coordinates private JSONL transactions, enforces rotation and retention, externalizes payloads, coalesces tool-call records, and serves bounded query and detail views. | These responsibilities form one transport-neutral audit-event lifecycle shared by MCP, REST, Human UI, jobs, workers, OAuth, downloads, and shell operations. |

Rejected ownership alternatives:

- top-level `audit.py`: it mixed a stable public contract with a 1,000-line
  implementation and made package-root placement look intentional.
- `utils`: audit policy includes redaction, retention, event semantics, payload
  references, and public query behavior rather than generic serialization.
- `executors` or `ui/http`: those layers emit and present audit events, but the
  same event store is shared across every delivery surface.

## Ownership review status

The following areas still require the same file-by-file ownership review:

- Human UI core and HTTP adapters.
- Remaining audit payload, release/build, and patch implementation modules
  currently at package root.
- Large stateful modules, which will be split only after package ownership is
  stable and each split has an independent test and CI closure.
