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

## License

MIT. See [LICENSE](LICENSE).
