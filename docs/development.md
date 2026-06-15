# Development

This page is for contributors working on `local-shell-mcp` itself.

## Local environment

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
uv run pre-commit install
```

Run checks:

```bash
uv run pre-commit run --all-files
uv run ruff check .
uv run pyright
uv run pytest -q
```

Run a local MCP server without OAuth:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp
```

Run the REST debug API:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode http
```

## Documentation development

The documentation site uses Material for MkDocs.

Install docs dependencies:

```bash
uv sync --group docs
```

Serve locally:

```bash
uv run mkdocs serve
```

Build strictly:

```bash
uv run mkdocs build --strict
```

The deployed site is built by the `Docs` GitHub Actions workflow from `docs/` and `mkdocs.yml`.

## Project layout

| Path | Purpose |
|---|---|
| `src/local_shell_mcp/main.py` | CLI parsing and mode dispatch. |
| `src/local_shell_mcp/server/` | Server app assembly for REST HTTP, MCP HTTP/stdio, shared public ASGI routes, MCP metadata, instructions, remote MCP registration, and tool watchdogs. |
| `src/local_shell_mcp/tools/contracts.py` | Shared tool registry contracts, context, HTTP route metadata, and local handler types. |
| `src/local_shell_mcp/tools/declarative.py` | Declarative tool registration that derives MCP registration and HTTP handlers from one typed function. |
| `src/local_shell_mcp/tools/discovery.py` | Runtime discovery of built-in tool registries. |
| `src/local_shell_mcp/tools/local_invocations.py` | HTTP adapter dispatch helper and routed REST auditing. |
| `src/local_shell_mcp/tools/registry/` | Category-specific MCP/REST tool registries discovered at runtime. |
| `src/local_shell_mcp/config/` | Pydantic settings, environment variables, YAML config, and configuration surface metadata. |
| `src/local_shell_mcp/oauth/` | OAuth middleware, server metadata, authorization flow, token handling, and HTTP route wrapping. |
| `src/local_shell_mcp/ops/` | Concrete filesystem, shell, patch, search, scan, todo, and shared operation helpers. |
| `src/local_shell_mcp/remote/` | Remote invite management, shared worker tool specs and services, worker routes, bundle assembly, and worker CLI helpers. |
| `src/local_shell_mcp/agent_bridge/` | External MCP and skill bridge, including shared service helpers used by MCP and REST adapters. |
| `src/local_shell_mcp/responses.py` | Shared response envelope builders for tool and remote endpoint responses. |
| `src/local_shell_mcp/audit.py` | Audit log writer, trimming, and routed tool-call audit helpers. |
| `tests/` | Unit, compatibility, and e2e tests. |
| `scripts/` | Generated-config, tool export, entrypoint, tunnel, and release helper scripts. |
| `vscode-extension/` | VS Code extension source and packaging metadata. |

## Implementation notes

- Tool registration is registry-based. Keep concrete behavior in `ops/`; registry modules adapt parameters, response envelopes, descriptions, and metadata.
- Transport app assembly lives in `mcp.app` and `http.app`.
- Static tools should use `DeclarativeToolRegistry` so MCP registration and HTTP handlers derive from one typed function. Declare the registry class first, then use `local_tool = RegistryClass.get_tool_decorator()` and `@local_tool(...)` for each tool so the registry has no second explicit tool list. Keep custom `http_routes()`, `http_handlers()`, or `register_mcp()` methods only when generated specs, dynamic tools, or runtime settings affect the surface.
- Large registry implementations may delegate focused MCP registration code to transport-specific companion modules, as `remote.py` does with `mcp.remote_tools`, so `tools.registry` stays focused on discovered registry definitions.
- Configuration surface metadata lives in `config.surface`.
- Do not add a second global tool table. MCP and REST surfaces should be derived from category registries.
- Routed tool calls are audited centrally. Avoid per-tool call logging unless the event is a lower-level subsystem event that is useful in addition to the routed call pair.
- MCP-over-HTTP requests are protected by OAuth unless `auth_mode=none` is configured.
- OAuth HTTP mode is split by responsibility: models/state, URL helpers, metadata endpoints, response serialization, dynamic client registration, authorization form/code flow, token/JWT validation, and ASGI route wrapping. Import from the focused `oauth.*` modules rather than a compatibility facade.
- Tool and remote endpoint responses should use shared envelope builders from `local_shell_mcp.responses`, with tool-specific handling layered in `tools.responses`.
- File tools avoid reading full binary files by default and enforce configured read/write limits.
- Operation modules that need managed temporary text files should use `ops.temp_file_ops` so temp pruning, size checks, and filename generation stay consistent.
- Remote workers run matching operation categories on the worker machine and return results through the control server.
- Remote registry adapters should call remote manager behavior through `remote.service` helpers rather than reaching into the manager directly.
- Remote worker proxy routes, HTTP handlers, and worker-side allowlists should derive from `remote.tool_specs` so new remote proxies are not registered in multiple places by hand.
- Agent bridge config is treated as external input and redacts configured secrets from status and error payloads.
- Agent bridge MCP and REST adapters should share behavior through `agent_bridge.service` instead of duplicating status, skill, and upstream MCP call logic.

## Release checks

Before cutting a release:

```bash
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
uv run mkdocs build --strict
```

Also test the Docker image and at least one MCP connection path before publishing.

## Selective upstream sync notes

Some upstream commits are intentionally recorded without porting their code when the current tree has a different policy or version line.

| Upstream commit | Decision | Rationale |
|---|---|---|
| `78fd6d5` Raise public shell timeout cap to 120 seconds | Skipped | The current configuration keeps `public_run_shell_max_timeout_s=60` and `public_tool_timeout_s=60`. Raising only the shell cap would be inconsistent with the existing tool watchdog policy, and this sync intentionally keeps the timeout behavior unchanged. |
| `8e5a988` Bump version to 2.3.0 | Skipped | The origin line is already at `3.5.0`; applying this upstream release-version bump would downgrade package and VS Code extension versions rather than port functionality. |
| `572d947` Prepare v2.3.1 release | Skipped | This is another upstream release-line update touching version metadata and release packaging. The origin line remains `3.5.0`, so applying it would downgrade release metadata instead of porting a feature. |
