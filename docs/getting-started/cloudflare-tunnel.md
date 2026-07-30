# Cloudflare Tunnel

A remote MCP client needs a public HTTPS endpoint. Cloudflare Tunnel can forward a public hostname to the local `local-shell-mcp` service while the server's own OAuth flow protects `/mcp`.

## Create the tunnel

In Cloudflare Zero Trust:

1. create a tunnel;
2. add a public hostname such as `mcp.example.com`;
3. route it to the service.

Use this target for a local process:

```text
http://127.0.0.1:8765
```

Use this target for the tunnel container in the repository's Compose setup:

```text
http://local-shell-mcp:8765
```

Add the public origin and tunnel token to `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=...
LOCAL_SHELL_MCP_BASE_URL=https://mcp.example.com
```

`LOCAL_SHELL_MCP_BASE_URL` is the origin only. Do not append `/mcp`.

## Run from a source checkout

```bash
scripts/run-with-cloudflare-tunnel.sh
```

For unattended use, run the helper with your preferred service manager.

## Run with Docker Compose

```bash
docker compose --profile tunnel up -d
```

## Verify

From another network, check:

```bash
curl -i https://mcp.example.com/healthz
```

Use this URL in the MCP client:

```text
https://mcp.example.com/mcp
```

## Common mistakes

- The connector URL does not end in `/mcp`.
- `LOCAL_SHELL_MCP_BASE_URL` incorrectly includes `/mcp`.
- The tunnel target uses the wrong hostname for local versus Compose deployment.
- The public hostname changed but `.env` still contains the old origin.
- OAuth is disabled on a public hostname.

Continue with [ChatGPT connector](chatgpt-connector.md) or see [Troubleshooting](../troubleshooting.md).
