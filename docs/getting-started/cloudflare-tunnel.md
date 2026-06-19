# Cloudflare Tunnel

ChatGPT custom MCP connectors need a public HTTPS endpoint. The recommended path is Cloudflare Tunnel: Cloudflare terminates HTTPS on your public hostname and forwards traffic to the local `local-shell-mcp` process.

Cloudflare Access is not required. `local-shell-mcp` uses its own OAuth approval flow for the MCP endpoint.

## Create the tunnel

In Cloudflare Zero Trust:

1. Create a Cloudflare Tunnel.
2. Add a public hostname such as `mcp.example.com`.
3. Route the hostname to the local service URL.

For the local service path, route to:

```text
http://127.0.0.1:8765
```

For Docker Compose with the bundled sidecar, route to:

```text
http://local-shell-mcp:8765
```

Copy the tunnel token and put it in `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=...
LOCAL_SHELL_MCP_BASE_URL=https://mcp.example.com
```

`LOCAL_SHELL_MCP_BASE_URL` must be the public origin exactly. Do not include `/mcp`.

## Run with the local helper

For a source checkout, run:

```bash
scripts/run-with-cloudflare-tunnel.sh
```

The helper loads `.env`, starts `uv run local-shell-mcp --mode mcp`, then starts `cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN"`.

When `cloudflared` exits, the helper stops the background server process. For long-running use, run the helper under systemd as shown in [Quickstart](quickstart.md).

## Run with Docker Compose

The Compose file includes an optional Cloudflare Tunnel sidecar:

```bash
docker compose --profile tunnel up -d
```

The sidecar reads `CLOUDFLARE_TUNNEL_TOKEN` from `.env` and sends tunnel traffic to the `local-shell-mcp` container.

## Verify routing

From a network outside the host, verify the public URL:

```bash
curl -i https://mcp.example.com/healthz
```

The MCP connector URL is:

```text
https://mcp.example.com/mcp
```

Common mistakes:

- `LOCAL_SHELL_MCP_BASE_URL` includes `/mcp`.
- Cloudflare routes to the wrong internal host: use `127.0.0.1` for local helper, `local-shell-mcp` for Compose sidecar.
- The tunnel hostname changes but `.env` still has the old origin.
- `LOCAL_SHELL_MCP_AUTH_MODE=none` is used on a public hostname.
