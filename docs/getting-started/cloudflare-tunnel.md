# Cloudflare Tunnel

ChatGPT custom connectors need a public HTTPS origin. The Compose file includes an optional `cloudflared` sidecar profile for Cloudflare Tunnel.

## Sidecar profile

Create a tunnel in Cloudflare Zero Trust, add a public hostname, and point it to:

```text
http://local-shell-mcp:8765
```

Put the tunnel token in `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=...
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Start both services:

```bash
docker compose --profile tunnel up -d
```

The public MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

This sidecar uses Cloudflare Tunnel only. It does not configure Cloudflare Access. The built-in OAuth server remains the authentication layer for public ChatGPT connector use.

## Source checkout helper

For a non-Docker source checkout, `scripts/run-with-cloudflare-tunnel.sh` starts `local-shell-mcp` with `uv` and then runs a named Cloudflare Tunnel in the same terminal session.

Set the required values in `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
CLOUDFLARE_TUNNEL_TOKEN=...
```

The Cloudflare public hostname should route to:

```text
http://127.0.0.1:8765
```

Run:

```bash
scripts/run-with-cloudflare-tunnel.sh
```

When `cloudflared` exits, the script also stops the background `local-shell-mcp` process. Use the Compose sidecar for long-running deployments.
