# local-shell-mcp

`local-shell-mcp` lets ChatGPT and other MCP clients work inside a controlled local workspace. It exposes shell, filesystem, search, patch, todo, audit, remote-worker, and agent-bridge tools through a ChatGPT-compatible MCP server with OAuth support.

Use it when you want an AI coding agent to inspect a project, edit files, run tests, operate Git, or delegate work to another machine without giving it direct access to your host.

## Documentation

The user guide is published at:

https://project.rijuyuezhu.top/local-shell-mcp/

The documentation source lives in [docs/](docs/) and is built with Material for MkDocs. Start with the [Quickstart](docs/getting-started/quickstart.md), then review [Security](docs/security.md) before exposing the service beyond localhost.

## Quick start

```bash
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
```

Expose the server through HTTPS, then add this MCP endpoint in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

For full shell and filesystem tools, enable ChatGPT Developer Mode before adding the custom MCP connector.

## Human interfaces

The HTTP service includes a native browser Human UI at `/ui`. It remains the default management surface. The same Dashboard, Remotes, persistent Terminals, Files, Todos, and Audit APIs are also available through the optional OpenTUI client:

```bash
local-shell-mcp --mode http
# In another terminal:
local-shell-mcp tui
```

Release archives and Docker images include a platform-native `local-shell-mcp-tui` sidecar. Source checkouts can build it from [`ui-opentui/`](ui-opentui/) with Bun. When a runtime is available, the browser UI also shows a separate OpenTUI Console without replacing the native browser panels. See the [Human interface guide](docs/guides/human-interface.md).

## License

MIT. See [LICENSE](LICENSE).
