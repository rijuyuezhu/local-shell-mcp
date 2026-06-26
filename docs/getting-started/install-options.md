# Install options

Choose the deployment path based on where commands should run.

## Local source checkout

Recommended for most Linux development machines:

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
cp .env.example .env
uv run local-shell-mcp --mode mcp
```

Use [Quickstart](quickstart.md) to add Cloudflare Tunnel and systemd.

## Release binary

Release binaries are useful when you do not want a source checkout or Python environment.

For binary deployments, set the workspace explicitly:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/project ./local-shell-mcp --mode mcp
```

The binary includes the Python server and default OAuth dependencies. It does not bundle host tools such as Git, tmux, shells, compilers, or LibreOffice; those come from the host system.

## Python package

```bash
pipx install local-shell-mcp
# or
pip install local-shell-mcp
```

Then run:

```bash
local-shell-mcp --mode mcp
```

## Docker Compose

Use Docker Compose when you want the tool runtime inside a container. Published Docker images support `linux/amd64` and `linux/arm64`:

```bash
cp .env.example .env
docker compose --profile tunnel up -d
```

See [Docker Compose](docker-compose.md).

## Docker without Compose

```bash
docker pull rijuyuezhu/local-shell-mcp:latest
mkdir -p "$PWD/workspace"
docker run --rm -it \
  -p 127.0.0.1:8765:8765 \
  --env-file .env \
  -v "$PWD/workspace:/workspace" \
  rijuyuezhu/local-shell-mcp:latest
```

You need a separate tunnel process when running Docker without the Compose sidecar. If you mount a host workspace directly, the entrypoint creates the runtime `agent` user from the mounted `/workspace` owner unless `DOCKER_AGENT_UID` or `DOCKER_AGENT_GID` is set.

## VS Code

The VS Code extension starts `local-shell-mcp` for the current workspace and provides commands to copy the MCP URL and setup prompt. See [VS Code](vscode.md).
