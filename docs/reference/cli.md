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

## Remote worker commands

The worker CLI has an explicit breaking-clean subcommand tree:

```text
local-shell-mcp worker enroll --server URL (--invite VALUE | --invite-stdin) [--name NAME] [--workdir PATH]
local-shell-mcp worker connect --server URL (--invite VALUE | --invite-stdin) [--name NAME] [--workdir PATH]
local-shell-mcp worker run
local-shell-mcp worker install-service [--no-start]
local-shell-mcp worker uninstall-service
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker status
local-shell-mcp worker logs [--lines N] [--follow]
local-shell-mcp worker update [--force]
```

`enroll` persists identity and exits. `connect` enrolls or resumes and stays in the foreground. `run` uses only the private persisted identity and is the command referenced by managed services and verified runtime re-exec. `--invite-stdin` accepts bounded UTF-8 from non-interactive stdin and avoids shell-history retention.

User-service management supports Linux `systemd --user` and macOS launchd. Windows returns a structured unsupported result. Service files contain no invite, worker access token, or server credential, and these commands remain local CLI functionality rather than MCP tools.

In most cases, create the invitation with `remote_admin(action="invite", args={...})` and paste the generated join command. The old flat `worker --server ...` form and `--persist` are not supported.
