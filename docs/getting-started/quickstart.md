# Quickstart

This guide starts `local-shell-mcp` as a local service, exposes it through Cloudflare Tunnel, then connects ChatGPT to the public `/mcp` endpoint.

The local service path is the recommended default because it works without the Docker image platform restriction and matches normal development workflows. Docker Compose is covered separately in [Docker Compose](docker-compose.md).

## Prerequisites

You need:

- A Linux host or VM that should run the shell/file/Git operations.
- `git`, `uv`, `python3`, `tmux`, `ripgrep`, and `cloudflared` available on that host.
- A Cloudflare Tunnel token for the public hostname.
- A workspace directory that you are willing to let an AI coding agent control.
- A ChatGPT plan and client mode that can add a custom MCP connector.

## 1. Clone and install dependencies

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
```

For a persistent service, keep this checkout in a stable path such as `~/Code/local-shell-mcp`.

## 2. Create `.env`

```bash
cp .env.example .env
```

Set at least these values:

```env
LOCAL_SHELL_MCP_MODE=mcp
LOCAL_SHELL_MCP_HOST=127.0.0.1
LOCAL_SHELL_MCP_PORT=8765
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/your/workspace
LOCAL_SHELL_MCP_STATE_DIR=/path/to/your/workspace/.local-shell-mcp
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

Notes:

- `LOCAL_SHELL_MCP_BASE_URL` is the public origin only, without `/mcp`.
- `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` gates the local approval page. Use a long random value.
- `LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false` keeps built-in workspace and command restrictions active.
- `LOCAL_SHELL_MCP_STATE_DIR` stores audit logs, temporary files, OAuth signing state, download-link state, and agent bridge config.

## 3. Start locally for a smoke test

```bash
set -a
. ./.env
set +a
uv run local-shell-mcp --mode mcp
```

In another terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Stop the foreground process after the health check succeeds.

## 4. Start with Cloudflare Tunnel

The repository includes a helper that starts `local-shell-mcp` with `uv`, then runs `cloudflared` in the same terminal:

```bash
scripts/run-with-cloudflare-tunnel.sh
```

The public MCP endpoint should be:

```text
https://your-public-host.example.com/mcp
```

See [Cloudflare Tunnel](cloudflare-tunnel.md) for the detailed Cloudflare side.

## 5. Install as a user systemd service

Create `~/.config/systemd/user/local-shell-mcp.service`:

```ini
[Unit]
Description=local-shell-mcp
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/YOU/Code/local-shell-mcp
ExecStart=/usr/bin/env bash scripts/run-with-cloudflare-tunnel.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Then run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now local-shell-mcp.service
journalctl --user -u local-shell-mcp.service -f -n 200
```

Use `systemctl --user restart local-shell-mcp.service` after changing `.env`.

## 6. Add the ChatGPT connector

Add a custom MCP connector with this URL:

```text
https://your-public-host.example.com/mcp
```

Complete the OAuth approval flow with the PIN from `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`. For the full shell/filesystem/Git tool surface, use a client mode that exposes full MCP tools.

## 7. Try a first prompt

```text
Use local-shell-mcp. First run session_start with workdir "." and summarize the returned session_id, workdir, git status, and instruction file paths. Do not change files yet.
```

Then try a repository workflow:

```text
Use local-shell-mcp to inspect this repository, run the tests, and summarize what you found before making any changes.
```

## 8. Watch audit logs

Default audit log path:

```bash
tail -F /path/to/your/workspace/.local-shell-mcp/audit_log/audit.jsonl | jq -C --unbuffered .
```

The audit log includes full tool inputs and outputs. Do not publish it without review.
