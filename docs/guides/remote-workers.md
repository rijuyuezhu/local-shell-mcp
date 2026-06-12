# Remote workers

Remote worker mode lets a machine behind NAT, a firewall, or an HPC login node connect back to the public control server using outbound HTTP(S). The remote machine does not need inbound SSH or an open port.

## How it works

1. The MCP client asks the control server to create a one-time invite.
2. You paste the generated command on the remote machine.
3. The remote worker downloads a worker bundle from the control server.
4. The worker registers, exchanges the invite for a token, and long-polls for jobs.
5. Remote tools run on the worker and return results through the control server.

Local tools keep their original behavior. Remote tools add a required `machine` argument.

```text
run_shell_tool(command="pwd")
remote_run_shell_tool(machine="npu-4card", command="pwd")
```

## Create an invite

Ask the connected MCP client:

```text
Use local-shell-mcp remote_invite with name=npu-4card and workdir=/home/cyh/FrameDiff.
```

The tool returns a pasteable command like:

```bash
curl -fsSL https://your-public-host.example.com/join | bash -s -- \
  --invite lsmcp_inv_xxxxx \
  --name npu-4card \
  --workdir /home/cyh/FrameDiff
```

Paste that command on the remote machine.

## Use an installed worker

If `local-shell-mcp` is already installed on the remote machine, the equivalent foreground command is:

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --invite lsmcp_inv_xxxxx \
  --name npu-4card \
  --workdir /home/cyh/FrameDiff
```

## Verify connection

After it connects:

```text
Use local-shell-mcp remote_list_machines.
```

Then try:

```text
Use local-shell-mcp remote_environment_info for machine=npu-4card.
```

## Common remote operations

- `remote_run_shell_tool` for one-shot shell and Git commands.
- `remote_shell_start`, `remote_shell_send`, and `remote_shell_read` for long-running remote sessions.
- `remote_read_file`, `remote_write_file`, and `remote_apply_patch` for remote file edits.
- `remote_grep_search`, `remote_glob_search`, and `remote_tree_view` for code navigation.

## Settings

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker routes and MCP tools |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | One-time invite lifetime |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | Long-poll heartbeat timeout |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | Control-side remote job result timeout |

Disable remote mode with `--remote-enabled false` or `LOCAL_SHELL_MCP_REMOTE_ENABLED=false`.
