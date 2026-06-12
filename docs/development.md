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
| `src/local_shell_mcp/mcp_app.py` | MCP stdio/HTTP transport startup and OAuth/remote ASGI route wrapping. |
| `src/local_shell_mcp/tools/base.py` | Shared tool registry, context, HTTP route metadata, and local handler types. |
| `src/local_shell_mcp/tools/discovery.py` | Runtime discovery of built-in tool registries. |
| `src/local_shell_mcp/tools/local_invocations.py` | HTTP adapter dispatch helper and routed REST auditing. |
| `src/local_shell_mcp/tools/registry/` | Category-specific MCP/REST tool registries. |
| `src/local_shell_mcp/http_app.py` | REST debug API and HTTP protocol adapter. |
| `src/local_shell_mcp/config/` | Pydantic settings, environment variables, YAML config, and generated metadata. |
| `src/local_shell_mcp/auth/` | Authentication middleware and OAuth server. |
| `src/local_shell_mcp/ops/` | Concrete filesystem, shell, patch, search, scan, and todo behavior. |
| `src/local_shell_mcp/remote/` | Remote invite management, worker routes, bundle assembly, and worker CLI helpers. |
| `src/local_shell_mcp/agent_bridge/` | External MCP and skill bridge. |
| `src/local_shell_mcp/audit.py` | Audit log writer, trimming, and routed tool-call audit helpers. |
| `tests/` | Unit, compatibility, and e2e tests. |
| `scripts/` | Development, probing, generated-config, entrypoint, and release helper scripts. |
| `vscode-extension/` | VS Code extension source and packaging metadata. |

## Implementation notes

- Tool registration is registry-based. Keep concrete behavior in `ops/`; registry modules adapt parameters, response envelopes, descriptions, and metadata.
- Do not add a second global tool table. MCP and REST surfaces should be derived from category registries.
- Routed tool calls are audited centrally. Avoid per-tool call logging unless the event is a lower-level subsystem event that is useful in addition to the routed call pair.
- MCP-over-HTTP requests are protected by OAuth unless `auth_mode=none` is configured.
- Tool results use a consistent `ok`, `message`, and `data` shape where possible.
- File tools avoid reading full binary files by default and enforce configured read/write limits.
- Remote workers run matching operation categories on the worker machine and return results through the control server.
- Agent bridge config is treated as external input and redacts configured secrets from status and error payloads.

## Release checks

Before cutting a release:

```bash
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
uv run mkdocs build --strict
```

Also test the Docker image and at least one MCP connection path before publishing.
