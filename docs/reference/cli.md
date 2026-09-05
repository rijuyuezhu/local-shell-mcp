# CLI reference

Every runtime mode is selected by an explicit argparse subcommand.

```text
workgate server [--config PATH] [--mode MODE] [--host HOST] [--port PORT] [--workspace-root PATH] [...]
```

Use the built-in help for exact parser output:

```bash
workgate --help
workgate server --help
workgate tui --help
workgate worker --help
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
WORKGATE_AUTH_MODE=none uv run workgate server --mode mcp
```

Run the REST debug API:

```bash
WORKGATE_AUTH_MODE=none uv run workgate server --mode http
```

Run with a specific workspace root:

```bash
WORKGATE_WORKSPACE_ROOT=/path/to/project uv run workgate server --mode mcp
```

## Boolean arguments

Boolean CLI values are explicit:

```bash
workgate server --allow-full-control false
workgate server --remote-enabled true
```

Every `WORKGATE_*` application setting has a matching CLI flag using lowercase dashed form. For example:

```text
WORKGATE_REMOTE_ENABLED -> --remote-enabled true
```

## Remote worker commands

The worker CLI has an explicit breaking-clean subcommand tree:

```text
workgate worker enroll --server URL (--invite VALUE | --invite-stdin) [--name NAME] [--workdir PATH]
workgate worker connect --server URL (--invite VALUE | --invite-stdin) [--name NAME] [--workdir PATH]
workgate worker run
workgate worker install-service [--no-start]
workgate worker uninstall-service
workgate worker start
workgate worker stop
workgate worker restart
workgate worker status
workgate worker logs [--lines N] [--follow]
workgate worker update [--force]
```

`enroll` persists identity and exits. `connect` enrolls or resumes and stays in the foreground. `run` uses only the private persisted identity and is the command referenced by managed services and verified runtime re-exec. `--invite-stdin` accepts bounded UTF-8 from non-interactive stdin and avoids shell-history retention.

User-service management supports Linux `systemd --user` and macOS launchd. Windows returns a structured unsupported result. Service files contain no invite, worker access token, or server credential, and these commands remain local CLI functionality rather than MCP tools.

In most cases, create the invitation with `remote_admin(action="invite", args={...})` and paste the generated join command. The old flat `worker --server ...` form and `--persist` are not supported.
