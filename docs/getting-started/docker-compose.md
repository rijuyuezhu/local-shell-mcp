# Docker Compose

Docker Compose is the recommended starting path because it keeps model-controlled tools inside a container.

## Environment file

Create `.env` from the example:

```bash
cp .env.example .env
```

Minimum public ChatGPT setup:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false
CLOUDFLARE_TUNNEL_TOKEN=
```

Docker Compose passes `.env` into the container with `env_file:`.

## Start

```bash
mkdir -p workspaces/default
docker compose up -d
```

Check status:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

## Mounted paths

The Compose file mounts these important paths:

| Host path or volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default/agent/workspace` | `/workspace` | Controlled project workspace |
| `./workspaces/default` | `/home` | Container home tree |
| `local-shell-mcp-credentials` | `/persist/credentials` | Optional persisted developer credentials |

`DOCKER_PERSISTENT_CREDENTIALS=true` persists common GitHub CLI, Git HTTPS, GitCode, SSH, `.netrc`, and GPG state across container rebuilds. Set it to `false` for more disposable authentication state.

## Workspace permissions

If the container cannot write `/workspace/.local-shell-mcp`, fix host ownership:

```bash
sudo mkdir -p workspaces/default/.local-shell-mcp
sudo chown -R 10001:10001 workspaces/default
docker compose restart local-shell-mcp
```

## Full-container mode

Keep this disabled by default:

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false
```

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` disables built-in workspace and command restrictions. Use it only in disposable containers or VMs.

## Stop and reset

Stop the service:

```bash
docker compose down
```

Remove the credential volume only when you intentionally want to discard persisted credentials:

```bash
docker volume rm local-shell-mcp-credentials
```
