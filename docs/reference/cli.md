# CLI reference

Running `local-shell-mcp` without a subcommand starts the server.

```text
local-shell-mcp [--config PATH] [--mode MODE] [--host HOST] [--port PORT] [--workspace-root PATH] [...]
```

Use the built-in help for exact parser output:

```bash
local-shell-mcp --help
local-shell-mcp worker --help
```

## Server modes

| Mode | Purpose |
|---|---|
| `mcp` | Serve MCP over HTTP at `/mcp`. This is the default public ChatGPT connector mode. |
| `stdio` | Run a stdio MCP server for local MCP clients. |
| `http` | Start the REST debug API only. |
| `both` | Reserved and exits with an error. Run separate processes if you need MCP and REST together. |

## Development examples

Run a local MCP server without OAuth:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp
```

Run the REST debug API:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode http
```

Run with a specific workspace root:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/project uv run local-shell-mcp --mode mcp
```

## Boolean arguments

Boolean CLI values are explicit:

```bash
local-shell-mcp --allow-full-control false
local-shell-mcp --remote-enabled true
```

Every `LOCAL_SHELL_MCP_*` application setting has a matching CLI flag using lowercase dashed form. For example:

```text
LOCAL_SHELL_MCP_REMOTE_ENABLED -> --remote-enabled true
```

## Remote worker command

A remote worker can be started directly when `local-shell-mcp` is installed on the remote machine:

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --invite lsmcp_inv_xxxxx \
  --name npu-4card \
  --workdir /home/cyh/FrameDiff
```

In most cases, create the invite with `remote_admin(action="invite", args={...})` and paste the generated command instead.
