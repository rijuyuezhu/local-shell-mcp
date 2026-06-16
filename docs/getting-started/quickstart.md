# Quickstart

This path starts `local-shell-mcp` with Docker Compose, then connects ChatGPT to the public `/mcp` endpoint.

## Prerequisites

You need:

- Docker and Docker Compose.
- A public HTTPS origin that forwards to the server when using ChatGPT over the public internet.
- A workspace directory that you are willing to let an AI coding agent control.

Local-only MCP clients can connect to localhost without a public tunnel. ChatGPT custom connectors require a public HTTPS origin for OAuth and MCP access.

## 1. Create the environment file

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
```

The bearer-token signing secret is generated automatically and persisted under the configured state directory.

## 2. Start the service

```bash
mkdir -p workspaces/default
docker compose up -d
```

Check that the container is running:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

## 3. Expose the server through HTTPS

For ChatGPT, your public endpoint should look like:

```text
https://your-public-host.example.com/mcp
```

The bundled Compose setup includes an optional Cloudflare Tunnel sidecar. See [Cloudflare Tunnel](cloudflare-tunnel.md) for details.

## 4. Add the ChatGPT connector

In ChatGPT, add a custom MCP connector with this URL:

```text
https://your-public-host.example.com/mcp
```

For full shell, filesystem, and Git-through-shell tools, enable Developer Mode before adding the custom MCP connector. Complete the OAuth flow using the PIN from `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`.

See [ChatGPT connector](chatgpt-connector.md) for a step-by-step setup.

## 5. Try a safe first prompt

```text
Use local-shell-mcp to inspect the workspace, run pwd, and summarize what tools are available before making any changes.
```

For a repository workflow:

```text
Use local-shell-mcp to inspect this repository, run the tests, and summarize what you found before making any changes.
```

## 6. Review activity

Audit records are written to the configured audit log. In the default Docker workspace:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit_log/audit.jsonl
```

The audit log includes full tool inputs and outputs. Treat it as sensitive session state.
