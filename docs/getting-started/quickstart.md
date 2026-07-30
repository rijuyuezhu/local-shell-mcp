# Quickstart

This guide runs `local-shell-mcp` locally, exposes it through Cloudflare Tunnel, and connects ChatGPT to the public `/mcp` endpoint.

For a container deployment, use [Docker Compose](docker-compose.md) instead.

## Prerequisites

You need a Linux host or VM with `git`, `uv`, Python 3.14+, `tmux`, `ripgrep`, and `cloudflared`; a project workspace; a Cloudflare Tunnel token; and a ChatGPT client that can add a custom MCP connector.

## 1. Install

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync
cp .env.example .env
```

Keep the checkout in a stable location if you plan to run it as a service.

## 2. Configure

Set these values in `.env`:

```env
LOCAL_SHELL_MCP_MODE=mcp
LOCAL_SHELL_MCP_HOST=127.0.0.1
LOCAL_SHELL_MCP_PORT=8765
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/your/workspace
LOCAL_SHELL_MCP_STATE_DIR=/path/to/your/workspace/.local-shell-mcp
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=replace-with-a-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

`LOCAL_SHELL_MCP_BASE_URL` is the public origin without `/mcp`. Keep the state directory private: it contains credentials and activity data used by the service.

For every setting and precedence rule, see [Configuration](../reference/configuration.md).

## 3. Smoke-test locally

```bash
set -a
. ./.env
set +a
uv run local-shell-mcp server --mode mcp
```

In another terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

A successful health check confirms that the local service is running.

## 4. Start the tunnel

The repository helper starts the server and Cloudflare Tunnel together:

```bash
scripts/run-with-cloudflare-tunnel.sh
```

Configure the tunnel hostname to route to `http://127.0.0.1:8765`. The public MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

See [Cloudflare Tunnel](cloudflare-tunnel.md) for the Cloudflare setup and common routing mistakes.

## 5. Keep it running

For a persistent Linux user service, create a systemd unit with the stable
checkout as its working directory:

```ini
[Service]
WorkingDirectory=/home/YOU/Code/local-shell-mcp
ExecStart=/usr/bin/env bash scripts/run-with-cloudflare-tunnel.sh
Restart=always
```

Enable the unit with `systemctl --user enable --now local-shell-mcp.service`.
Use `journalctl --user -u local-shell-mcp.service -f` to inspect its logs.

## 6. Connect ChatGPT

Add a custom MCP connector using the public `/mcp` URL, then complete OAuth approval with the admin PIN from `.env`. Use a client mode that exposes the full MCP tool surface when you need shell, file, and Git operations.

See [ChatGPT connector](chatgpt-connector.md) for the exact UI flow.

## 7. Try a first task

```text
Use local-shell-mcp. Start a session in my project workspace, inspect the repository and its instruction files, then summarize the environment and Git status. Do not change files yet.
```

Continue with [Common workflows](../guides/common-workflows.md), or open the browser interface described in [Human interface](../guides/human-interface.md).
