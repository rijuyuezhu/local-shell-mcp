# Usage

This guide explains how to connect clients, run the server, use remote workers, and debug common issues.

## ChatGPT connector setup

For full shell, filesystem, and Git tools, enable ChatGPT Developer Mode and add a custom MCP connector.

1. Start `local-shell-mcp` and expose it through a public HTTPS origin.
2. Confirm `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` exactly matches that public origin.
3. In ChatGPT settings, go to Connectors.
4. Enable Developer Mode under Advanced.
5. Add a custom MCP connector.
6. Use the MCP URL:

```text
https://your-public-host.example.com/mcp
```

7. Complete the OAuth flow using `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`.
8. Refresh the connector tool list after server changes.

Regular ChatGPT connectors and Deep Research-style clients expect read-only `search` and `fetch` tools. Full write/execute tools require Developer Mode or another full MCP client.

After connecting, test with:

```text
Use local-shell-mcp to run pwd and tell me the output.
```

Watch server-side activity:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit.jsonl
```

A successful shell call should produce audit events such as `run_shell_start` and `run_shell_end`.

## CLI modes

Running `local-shell-mcp` without a subcommand starts the server:

```text
local-shell-mcp [--mode {mcp,http,stdio}] [--config PATH] [--remote | --no-remote]
```

Server options:

- `--mode {mcp,http,stdio}` overrides `LOCAL_SHELL_MCP_MODE`.
- `--config PATH` sets `LOCAL_SHELL_MCP_CONFIG` before loading settings.
- `--remote` enables remote worker routes and tools.
- `--no-remote` disables remote worker routes and tools.

Use the built-in help for exact parser output:

```bash
local-shell-mcp --help
local-shell-mcp worker --help
```

## Configuration

Environment variables use the `LOCAL_SHELL_MCP_` prefix. YAML config can also be passed with `--config`:

```bash
local-shell-mcp --config config.example.yaml --mode mcp
```

Common settings:

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_HOST` | `0.0.0.0` | Bind host |
| `LOCAL_SHELL_MCP_PORT` | `8765` | Bind port |
| `LOCAL_SHELL_MCP_MODE` | `mcp` | `mcp`, `http`, or `stdio` |
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `/workspace` | Root for normal file and command operations |
| `LOCAL_SHELL_MCP_AUTH_MODE` | `oauth` | `oauth` or `none` |
| `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `true` | Allow localhost requests without bearer auth |
| `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `false` | Require auth for MCP initialize/list-tools discovery calls |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | unset | Public HTTPS origin used in OAuth metadata |
| `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | unset | PIN required to approve OAuth authorization |
| `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | `dev-change-me` | Secret used to sign bearer tokens |
| `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | Bearer token lifetime in seconds; `0` means no expiry |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `false` | Disable built-in workspace and command restrictions; intended only for disposable containers/VMs |
| `DOCKER_RUN_AS_ROOT` | `false` | Docker entrypoint escape hatch to run the MCP server as root instead of `agent`; prefer explicit `sudo` inside commands |
| `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `3600` | Maximum command timeout |
| `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `200000` | Command output truncation limit |
| `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | `512000` | Per-file read limit |
| `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | `5000000` | Per-file write/edit limit |
| `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` | Concurrent command limit |
| `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Persistent shell session limit |
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker routes and tools |
| `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | `true` | Enable agent capability bridge tools |
| `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `/home/agent/local-shell-mcp-config` | Read-only capability config directory |

See `config.example.yaml` and `.env.example` for deployment-oriented examples.

## Remote worker mode

Remote worker mode is enabled by default. It lets machines behind NAT, firewalls, or restricted HPC login environments connect back to the public control server using outbound HTTP(S). The remote machine does not need an inbound port or SSH access from the MCP client.

Local tools keep their original behavior. Remote tools add a required `machine` argument:

```text
run_shell_tool(command="pwd")
remote_run_shell_tool(machine="npu-4card", command="pwd")
```

Create a one-time invite from ChatGPT or any MCP client:

```text
Use local-shell-mcp remote_invite with name=npu-4card and workdir=/home/cyh/FrameDiff.
```

The tool returns a pasteable command like:

```bash
curl -fsSL https://your-public-host.example.com/join | bash -s --   --invite lsmcp_inv_xxxxx   --name npu-4card   --workdir /home/cyh/FrameDiff
```

Paste that command on the remote machine. The join script downloads a worker bundle from the control server at `/remote/worker-bundle.tgz`, so the remote side uses the same code snapshot as the control server and does not need GitHub or PyPI access.

The worker registers once, exchanges the invite for a worker token, and then long-polls the control server for jobs. The default mode is foreground and temporary; press `Ctrl-C` on the remote machine to disconnect. Add `--background` to the generated command for a simple `nohup` background worker. `--persist` is accepted for future user-service installation support.

If `local-shell-mcp` is already installed on the remote machine, the equivalent foreground worker command is:

```bash
local-shell-mcp worker   --server https://your-public-host.example.com   --invite lsmcp_inv_xxxxx   --name npu-4card   --workdir /home/cyh/FrameDiff
```

After it connects:

```text
Use local-shell-mcp remote_list_machines.
```

Then use near-parity remote tools such as `remote_run_shell_tool`, `remote_read_file`, `remote_write_file`, `remote_grep_search`, `remote_git_pull_tool`, or `remote_shell_start`.

Remote settings:

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker routes and MCP tools |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | One-time invite lifetime |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | Long-poll heartbeat timeout |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | Control-side remote job result timeout |

Disable remote mode with `--no-remote` or `LOCAL_SHELL_MCP_REMOTE_ENABLED=false`.

## Agent capability bridge

`local-shell-mcp` can expose externally synced agent capabilities from a read-only config directory inside the container. With the default Docker Compose layout, write files on the host under:

```text
workspaces/default/agent/local-shell-mcp-config/
  config.json
  skills/
    <skill-name>/
      SKILL.md
```

The container reads the same files from:

```text
/home/agent/local-shell-mcp-config
```

The default Compose workspace mount is read-write; `local-shell-mcp` does not mutate this directory. Mount it read-only in your deployment if you want filesystem enforcement.

A normalized `config.json` can include MCP servers, skills, and dynamic tool toggles:

```json
{
  "version": 1,
  "mcpServers": {
    "docs": {
      "type": "http",
      "url": "https://example.com/mcp",
      "enabled": true
    }
  },
  "skills": {
    "enabled": true,
    "directory": "skills"
  },
  "dynamicTools": {
    "mcp": true,
    "skills": true
  }
}
```

Bridge behavior:

- `agent_config_status` reports the loaded config, skills, MCP servers, dynamic tools, and probe errors with configured secrets redacted.
- `activate_agent_skill` returns the content of a discovered `SKILL.md`.
- `call_agent_mcp_tool` calls a configured external MCP tool through a fixed bridge endpoint.
- When dynamic tools are enabled, skills and external MCP tools can appear as first-class MCP tools.
- Stdio MCP server commands run inside the container for Docker deployments. Docker-free binary deployments run them in the same environment as `local-shell-mcp`, which may be the host.

## Git access

Prefer credentials that are narrowly scoped to the repositories the model should touch.

### Deploy key

Create a deploy key restricted to one repository:

```bash
ssh-keygen -t ed25519 -f ./deploy_key_project -C local-shell-mcp-project
```

Add the public key to the GitHub repository deploy keys with the minimum required permissions. Mount the private key only if you accept that the model-controlled container can use it:

```yaml
volumes:
  - ./deploy_key_project:/home/agent/.ssh/id_ed25519:ro
```

### SSH agent socket

This avoids copying a private key into the container, but the container can still ask the agent to sign Git operations:

```yaml
volumes:
  - ${SSH_AUTH_SOCK}:${SSH_AUTH_SOCK}
environment:
  SSH_AUTH_SOCK: ${SSH_AUTH_SOCK}
```

Use a key that only has access to repositories you are willing to expose.

## REST debug API

The normal MCP server runs with:

```bash
local-shell-mcp --mode mcp
```

For local-only debugging, start the REST API:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none local-shell-mcp --mode http
```

Example:

```bash
curl -s http://127.0.0.1:8765/tools/run_shell   -H 'content-type: application/json'   -d '{"command":"pwd && ls -la","cwd":"."}' | jq
```

Do not expose HTTP debug mode publicly.

## Troubleshooting

If ChatGPT says it connected but no tools are available:

1. Confirm Developer Mode is enabled for full MCP tools.
2. Delete and re-add the connector after server changes.
3. Confirm `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` exactly matches the public HTTPS origin.
4. Check `/mcp` with a standard MCP client.
5. Watch `/workspace/.local-shell-mcp/audit.jsonl`.

If OAuth succeeds but tool listing fails, check container logs:

```bash
docker compose logs --tail=200 local-shell-mcp
```

If you see `Task group is not initialized`, update to a newer image that includes the MCP lifespan fix.

You can probe the public endpoint from a machine with the project installed:

```bash
python scripts/probe-mcp.py https://your-public-host.example.com --pin "$LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN"
```

The probe should report successful unauthenticated `initialize/list_tools` and a successful authenticated `environment_info` call.
