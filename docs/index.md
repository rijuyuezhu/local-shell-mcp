# local-shell-mcp

`local-shell-mcp` gives ChatGPT and other MCP clients controlled access to a machine you own. It exposes shell, filesystem, search, patch, audit, remote-worker, and agent-bridge capabilities through an MCP server with OAuth support.

## Start here

Most users should start with the local service path:

1. Install or clone `local-shell-mcp` on the machine that should run commands.
2. Copy `.env.example` to `.env` and set the public URL, OAuth mode, and approval PIN.
3. Expose the server through Cloudflare Tunnel.
4. Add the `/mcp` endpoint as a ChatGPT custom connector.

See [Quickstart](getting-started/quickstart.md) for the complete flow.

Docker Compose is still supported, but the published Docker image is currently `linux/amd64`. Use it when you specifically want the model-controlled tools inside a container and your host can run the x64 image.

## What you get

- A ChatGPT-compatible MCP endpoint at `/mcp`.
- Built-in OAuth approval for public deployments.
- Local shell, Python, file, search, patch, todo, audit, and download-link tools.
- Optional remote workers for running the same tool categories on another machine.
- Optional agent bridge for exposing external MCP servers and Markdown skills through this server.
- A VS Code extension for starting the server against the current workspace.

## Important pages

| Need | Page |
|---|---|
| Set up the service | [Quickstart](getting-started/quickstart.md) |
| Expose the endpoint | [Cloudflare Tunnel](getting-started/cloudflare-tunnel.md) |
| Add ChatGPT | [ChatGPT connector](getting-started/chatgpt-connector.md) |
| Use Docker instead | [Docker Compose](getting-started/docker-compose.md) |
| Run work on another machine | [Remote workers](guides/remote-workers.md) |
| Add external MCP servers or skills | [Agent capability bridge](guides/agent-bridge.md) |
| Check every setting | [Configuration reference](reference/configuration.md) |
| Check every tool | [Tools reference](reference/tools.md) |
| Debug a local checkout | [Development](development.md) |

## Safety model

This project intentionally gives an AI client access to real shell and filesystem tools. Keep public deployments behind OAuth, set a long random approval PIN, review the configured workspace root, and leave full-control mode disabled unless the server runs in a disposable container or VM.

Audit logs include full tool inputs and outputs. Treat the state directory as sensitive session data.
