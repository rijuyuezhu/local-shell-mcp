# Remote workers

Remote workers let the control server run the same shell, Python, file, search, patch, and transfer operations on another machine. Use them when the connected ChatGPT session should coordinate work on a GPU box, lab machine, build host, or remote checkout while keeping one public MCP connector.

## How it works

1. The MCP client calls `remote_invite` on the control server.
2. The server returns a one-time shell command containing an invite code.
3. You paste that command on the remote machine.
4. The remote machine downloads a worker bundle from the control server, starts the worker, registers once, then long-polls for jobs.
5. The MCP client uses `remote_*` tools with the registered machine name.

Remote worker enrollment routes are public so the worker can join. Treat invite commands as sensitive and short-lived.

## Requirements

Control server:

- Public `LOCAL_SHELL_MCP_BASE_URL` must be reachable from the remote machine.
- `LOCAL_SHELL_MCP_REMOTE_ENABLED=true`.
- OAuth still protects normal MCP/REST tool calls.

Remote machine:

- `python3`, `curl`, and `tar` are required by the join script.
- The selected working directory should exist or be creatable by the user running the worker.
- The worker inherits the remote machine's installed tools such as Git, compilers, CUDA tooling, and package managers.

## Create an invite

Ask the connected MCP client:

```text
Use local-shell-mcp to create a remote worker invite named gpu1 with workdir /home/me/project.
```

Equivalent tool call shape:

```json
{
  "name": "gpu1",
  "workdir": "/home/me/project",
  "ttl_s": 600
}
```

The server returns a command like:

```bash
curl -fsSL https://your-public-host.example.com/join | bash -s -- --invite lsmcp_inv_xxxxx --name gpu1 --workdir /home/me/project
```

Paste it on the remote machine. The generated invite is one-time use and expires after the configured TTL.

## Start an installed worker manually

If `local-shell-mcp` is already installed on the remote machine, run:

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --invite lsmcp_inv_xxxxx \
  --name gpu1 \
  --workdir /home/me/project
```

The `--server` value is the public origin, not `/mcp`.

## Verify connection

Ask the MCP client:

```text
Use local-shell-mcp to list remote machines, then run remote_environment_info on gpu1.
```

The normal flow before remote edits is:

1. `remote_list_machines`
2. `remote_environment_info`
3. `remote(op="tree")` or `remote(op="list_files")`
4. `remote(op="search")` or `remote(op="read")`
5. `remote(op="bash")` or `remote(op="edit_lines")`/`remote(op="apply_patch")`

## Run remote commands

Example prompt:

```text
Use local-shell-mcp on remote machine gpu1. Inspect /home/me/project, run git status, then run the test command you find in the project docs. Report results before editing files.
```

Use persistent remote shells for long-running servers, training runs, watchers, and REPL-like sessions:

```text
Start a persistent shell on remote machine gpu1 in /home/me/project to run the dev server. Then read the first 200 lines of output.
```

## Transfer files and directories

Use remote transfer tools for binary files, build artifacts, datasets, and larger trees:

- `remote_push_file` / `remote_push_dir`: local workspace to remote worker.
- `remote_pull_file` / `remote_pull_dir`: remote worker to local workspace.
- `remote_copy_file` / `remote_copy_dir`: one remote worker to another through the control server.

Example prompt:

```text
Use local-shell-mcp to pull /home/me/project/results/report.html from gpu1 into ./artifacts/report.html.
```

## Revoke a worker

When a worker should no longer receive jobs:

```text
Use local-shell-mcp to revoke remote machine gpu1.
```

This removes the worker from the control server. Reconnect it with a new invite if needed.

## Settings

| Setting | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker routes and MCP tools |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | Default one-time invite lifetime |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | Long-poll heartbeat timeout |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | Control-side remote job result timeout |

Disable remote mode with `--remote-enabled false` or `LOCAL_SHELL_MCP_REMOTE_ENABLED=false`.
