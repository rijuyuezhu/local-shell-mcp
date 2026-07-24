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

The repository is being migrated to this structure incrementally. The MCP
executor now lives in its final `executors/mcp` package. `server/http` remains a
transitional REST/UI location until the later executor and UI moves complete.
New domain code must not depend on the transitional package.

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

## Ownership review status

The following areas still require the same file-by-file ownership review:

- REST executor package.
- Human UI core and HTTP adapters.
- Terminal, audit, release/build, and patch implementation modules currently at
  package root.
- Large stateful modules, which will be split only after package ownership is
  stable and each split has an independent test and CI closure.
