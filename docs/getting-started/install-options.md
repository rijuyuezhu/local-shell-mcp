# Install options

Docker Compose is the recommended starting point for most users. Other deployment paths are available when Docker is not appropriate.

## Docker Compose

Use Docker Compose when you want the model-controlled tools contained in a dedicated environment:

```bash
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
```

See [Docker Compose](docker-compose.md) for details.

## Docker without Compose

```bash
docker pull rijuyuezhu/local-shell-mcp:latest
mkdir -p workspace
docker run -d \
  --name local-shell-mcp \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/workspace:/workspace" \
  rijuyuezhu/local-shell-mcp:latest
```

Check the restart policy:

```bash
docker inspect local-shell-mcp --format '{{.HostConfig.RestartPolicy.Name}}'
```

It should be `unless-stopped`.

## Release binary

Download a Docker-free executable from GitHub Releases when you do not want to run Docker. Release assets are built for Linux, macOS, and Windows on x86_64 and ARM64/aarch64.

Start it directly:

```bash
./local-shell-mcp --mode mcp
```

On Windows PowerShell:

```powershell
.\local-shell-mcp.exe --mode mcp
```

For binary deployments, set `LOCAL_SHELL_MCP_WORKSPACE_ROOT` to the directory you want the tools to control:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/project ./local-shell-mcp --mode mcp
```

The binary includes the Python server and default OAuth dependencies. It does not bundle host tools such as Git, tmux, shells, compilers, or LibreOffice; those are taken from the host system.

## Install from source

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp
```

For contributor setup, see [Development](../development.md).
