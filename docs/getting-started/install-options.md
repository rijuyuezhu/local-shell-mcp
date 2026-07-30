# Install options

Choose where commands should run and how much isolation you need.

## Local source checkout

Best for development machines and contributors:

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync
cp .env.example .env
uv run local-shell-mcp server --mode mcp
```

Continue with the [Quickstart](quickstart.md) to configure OAuth, HTTPS, and a client connection.

## Python package

Best when you want a normal Python installation without a source checkout:

```bash
pipx install local-shell-mcp
# or
pip install local-shell-mcp

local-shell-mcp server --mode mcp
```

Platform-specific wheels include the native OpenTUI client on supported platforms. A universal wheel may provide only the server; the browser interface remains available.

## Release archive

Best for a self-contained installation without managing a Python environment. Download the archive for your operating system and architecture from the GitHub release, then set an explicit workspace:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/project   ./local-shell-mcp server --mode mcp
```

Host commands such as Git, compilers, package managers, and shells still need to be installed on the machine where the server runs.

## Docker Compose

Best for a more disposable and isolated tool environment. Published images support Linux `amd64` and `arm64`:

```bash
cp .env.example .env
mkdir -p workspaces/default/agent/workspace
docker compose --profile tunnel up -d
```

See [Docker Compose](docker-compose.md) for workspace mounts, permissions, and reset steps.

## Docker without Compose

```bash
docker pull rijuyuezhu/local-shell-mcp:latest
mkdir -p "$PWD/workspace"
docker run --rm -it   -p 127.0.0.1:8765:8765   --env-file .env   -v "$PWD/workspace:/workspace"   rijuyuezhu/local-shell-mcp:latest
```

Run an HTTPS tunnel separately and make sure the mounted workspace is writable by the container user.

## VS Code

The VS Code extension starts the server for the current workspace and can copy the MCP URL and setup prompt. See [VS Code](vscode.md).
