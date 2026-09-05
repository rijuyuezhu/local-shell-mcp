# Quickstart

This guide runs `workgate` locally, exposes it through Cloudflare Tunnel, and connects ChatGPT to the public `/mcp` endpoint.

## Prerequisites

You need:

- a Linux or macOS host with `git`, `uv`, Python 3.14+, `tmux`, `ripgrep`, and `cloudflared`;
- a project directory that the agent may read and modify—use an existing checkout, or create an empty directory such as `mkdir -p ~/Projects/my-project`;
- a Cloudflare account and a domain managed by Cloudflare—follow Cloudflare's [domain onboarding guide](https://developers.cloudflare.com/fundamentals/manage-domains/add-site/) when starting with a domain from another registrar; and
- a ChatGPT plan and role that can add a custom MCP app.

!!! note "ChatGPT plan availability"
    Full read/write MCP currently requires Business (formerly Team), Enterprise, or Edu. Pro supports read/fetch-only custom MCP connections. Check [OpenAI's current availability notes](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta) before setup.

[Step 4](#4-create-and-start-the-tunnel) shows where to create the tunnel and obtain its token. On macOS, install missing command-line tools with Homebrew or another package manager. The service example later in this guide uses Linux systemd; macOS users can run the helper in the foreground or configure it with launchd.

## 1. Install

```bash
git clone https://github.com/rijuyuezhu/workgate.git
cd workgate
uv sync
cp .env.example .env
```

Keep the checkout in a stable location if you plan to run it as a service.

## 2. Configure

Set these values in `.env`:

```env
WORKGATE_MODE=mcp
WORKGATE_HOST=127.0.0.1
WORKGATE_PORT=8765
WORKGATE_WORKSPACE_ROOT=/path/to/your/workspace
WORKGATE_STATE_DIR=/path/to/your/workspace/.workgate
WORKGATE_BASE_URL=https://your-public-host.example.com
WORKGATE_AUTH_MODE=oauth
WORKGATE_OAUTH_ADMIN_PIN=replace-with-a-long-random-pin
WORKGATE_ALLOW_FULL_CONTROL=false
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

`WORKGATE_BASE_URL` is the public origin without `/mcp`. Keep the state directory private: it contains credentials and activity data used by the service.

Leave the example `CLOUDFLARE_TUNNEL_TOKEN` value in place for now. You will replace it with the token copied from Cloudflare in [Step 4](#4-create-and-start-the-tunnel); the detailed dashboard flow is in [Cloudflare Tunnel](cloudflare-tunnel.md).

For every setting and precedence rule, see [Configuration](../reference/configuration.md).

## 3. Smoke-test locally

```bash
set -a
. ./.env
set +a
uv run workgate server --mode mcp
```

In another terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

A successful health check confirms that the local service is running. Stop the
foreground server with Ctrl+C before continuing: the tunnel helper starts its
own server on the same address.

## 4. Create and start the tunnel

Follow [Cloudflare Tunnel](cloudflare-tunnel.md) to:

1. create a remotely managed tunnel in the Cloudflare dashboard;
2. add a published application route from your public hostname to `http://127.0.0.1:8765`;
3. copy the tunnel token into `CLOUDFLARE_TUNNEL_TOKEN` in `.env`; and
4. set `WORKGATE_BASE_URL` to the same public HTTPS origin.

Then start the server and tunnel together:

```bash
scripts/run-with-cloudflare-tunnel.sh
```

The public MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

The Cloudflare guide also covers common routing mistakes.

## 5. Keep it running

For a persistent Linux user service, create
`~/.config/systemd/user/workgate.service` with the stable checkout as its
working directory:

```ini
[Unit]
Description=workgate
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/YOU/Code/workgate
ExecStart=/usr/bin/env bash scripts/run-with-cloudflare-tunnel.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Reload the user manager, enable the service, and inspect its logs:

```bash
systemctl --user daemon-reload
systemctl --user enable --now workgate.service
journalctl --user -u workgate.service -f -n 200
```

Use `systemctl --user restart workgate.service` after changing `.env`.

## 6. Connect ChatGPT

Add a custom MCP connector using the public `/mcp` URL, then complete OAuth approval with the admin PIN from `.env`. Use a client mode that exposes the full MCP tool surface when you need shell, file, and Git operations.

See [ChatGPT connector](chatgpt-connector.md) for the exact UI flow.

## 7. Try a first task

```text
Use workgate. Start a session in my project workspace, inspect the repository and its instruction files, then summarize the environment and Git status. Do not change files yet.
```

Continue with [Common workflows](../guides/common-workflows.md), or open the browser interface described in [Human interface](../guides/human-interface.md).
