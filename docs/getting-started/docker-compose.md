# Docker Compose

Docker Compose runs the model-controlled tools inside a container. Use it when you want a more disposable execution environment or want container-level separation from the host.

The published Docker image is an Ubuntu 26.04 runtime image with Python and project dependencies installed by `uv`. Release images are published for `linux/amd64` and `linux/arm64` and are combined into a multi-arch manifest.

## Create `.env`

```bash
cp .env.example .env
```

Minimum public setup:

```env
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

Docker Compose passes `.env` into the container with `env_file:`. The Cloudflare sidecar also reads the tunnel token from the same file.

Leave `DOCKER_AGENT_UID` and `DOCKER_AGENT_GID` empty for the default Compose flow. On startup, the Docker entrypoint creates the `agent` user from the owner of the mounted `/workspace` directory. Set those variables only when you need to override the detected host UID/GID.

## Start

```bash
mkdir -p workspaces/default/agent/workspace
docker compose --profile tunnel up -d
```

Check status:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
docker compose logs --tail=100 cloudflared
curl -i http://127.0.0.1:8765/healthz
```

## Mounted paths

| Host path or volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default/agent/workspace` | `/workspace` | Controlled project workspace |
| `./workspaces/default` | `/home` | Container home tree |
| `local-shell-mcp-credentials` | `/persist/credentials` | Optional persisted developer credentials |

`DOCKER_PERSISTENT_CREDENTIALS=true` persists common GitHub CLI, Git HTTPS, GitCode, SSH, `.netrc`, and GPG state across container rebuilds. Set it to `false` for more disposable authentication state.

## Workspace permissions

By default, the entrypoint detects the owner of the mounted `/workspace` directory and creates the runtime `agent` user with that UID/GID. For the standard setup, this means the files created by the container match the host user that created `./workspaces/default/agent/workspace`.

If the container cannot write `/workspace/.local-shell-mcp`, first check the host-side owner:

```bash
mkdir -p workspaces/default/agent/workspace
stat -c '%u:%g %n' workspaces/default/agent/workspace
```

Then either fix the host ownership or override the runtime agent identity in `.env`:

```env
DOCKER_AGENT_UID=1000
DOCKER_AGENT_GID=1000
```

Restart after changing ownership or `.env`:

```bash
docker compose restart local-shell-mcp
```

## Full-control mode

Keep this disabled by default:

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
```

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=true` disables built-in workspace and command restrictions. Use it only in disposable containers or VMs.

## Stop and reset

```bash
docker compose down
```

Remove the credential volume only when you intentionally want to discard persisted credentials:

```bash
docker volume rm local-shell-mcp-credentials
```
