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

Host commands such as Git, compilers, package managers, and shells still need to be installed on the machine where the server runs. POSIX persistent shells also require tmux.
