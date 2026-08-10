# Docker Compose

Docker Compose runs model-controlled tools inside a container. Use it for a disposable environment or when you want separation from the host. Published images support Linux `amd64` and `arm64`.

## Configure

```bash
cp .env.example .env
```

Set at least:

```env
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=replace-with-a-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

Replace `your-cloudflare-tunnel-token` after following [Cloudflare Tunnel](cloudflare-tunnel.md) to create the tunnel and copy its token.

Leave `DOCKER_AGENT_UID` and `DOCKER_AGENT_GID` empty for the normal setup. Set them only when the mounted workspace needs a specific host UID/GID.

## Start

```bash
mkdir -p workspaces/default/agent/workspace
docker compose --profile tunnel up -d
```

Check the service and tunnel:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
docker compose logs --tail=100 cloudflared
curl -i http://127.0.0.1:8765/healthz
```

The `tunnel` profile is optional. Omit `--profile tunnel` when HTTPS is provided separately.

## Mounted data

| Host path or volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default/agent/workspace` | `/workspace` | Controlled project workspace |
| `./workspaces/default` | `/home` | Container home and service state |
| `local-shell-mcp-credentials` | `/persist/credentials` | Optional persisted developer credentials |

`DOCKER_PERSISTENT_CREDENTIALS=false` only disables creation and refresh of credential redirects into `/persist/credentials`. It does not erase existing Git, SSH, or other login state: `/home` is still backed by `./workspaces/default`, and redirects or files already present under `/home/agent` remain available.

To discard existing developer credentials, stop the stack, remove the corresponding credential files or symlinks under `workspaces/default/agent` (for example `.config/gh`, `.gitconfig`, `.git-credentials`, `.ssh`, `.netrc`, and `.gnupg`), and remove the Compose credential volume with `docker compose down --volumes`. If the entire container home should be disposable across recreations, remove or replace the `./workspaces/default:/home` bind mount as well.

## Fix workspace permissions

If the service cannot write the workspace or its `.local-shell-mcp` state directory, inspect the host owner:

```bash
stat -c '%u:%g %n' workspaces/default/agent/workspace
```

Fix the host ownership, or set matching values in `.env`:

```env
DOCKER_AGENT_UID=1000
DOCKER_AGENT_GID=1000
```

Then restart:

```bash
docker compose restart local-shell-mcp
```

## Security

Keep full-control mode disabled unless the container or VM is disposable:

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
```

Container isolation is not a substitute for OAuth, narrow workspace mounts, or careful credential handling. Review [Security](../security.md) before public exposure.

## Stop or reset

```bash
docker compose down
```

Remove the Compose-managed credential volume only when you intentionally want to discard it:

```bash
docker compose down --volumes
```

This does not erase credential files or symlinks retained by the `/home` bind mount; clean those separately as described under [Mounted data](#mounted-data).
