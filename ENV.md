# Environment variable reference

This is the complete reference for settings that can be supplied through the process environment. For Docker Compose deployments, copy [.env.example](.env.example) to `.env`; the compose file requires that file and passes it to the main container with `env_file:`. For task-oriented setup instructions, start with [INSTALL.md](INSTALL.md) and [USAGE.md](USAGE.md).

## Naming convention

- `LOCAL_SHELL_MCP_*` configures the local-shell-mcp application.
- `DOCKER_*` configures Docker image entrypoint behavior before the application starts.
- Third-party variables such as `CLOUDFLARE_TUNNEL_TOKEN`, `TUNNEL_HOSTNAME`, and `SSH_AUTH_SOCK` keep their upstream names.

## Application configuration precedence

Only application settings participate in this precedence chain:

```text
defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments
```

The YAML config file is optional. Prefer `LOCAL_SHELL_MCP_*` variables or CLI arguments for new deployments. `--config PATH` and `LOCAL_SHELL_MCP_CONFIG` select the optional config file.

## Application settings

| Environment variable | CLI argument | Default | Description |
|---|---|---:|---|
| `LOCAL_SHELL_MCP_HOST` | `--host` | `0.0.0.0` | Bind host for HTTP/MCP transports. |
| `LOCAL_SHELL_MCP_PORT` | `--port` | `8765` | Bind port. |
| `LOCAL_SHELL_MCP_MODE` | `--mode` | `mcp` | Server mode: `mcp`, `http`, or `stdio`. |
| `LOCAL_SHELL_MCP_CONFIG` | `--config` | unset | Optional YAML config path. Prefer env/CLI for new deployments. |
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `--workspace-root` | `/workspace` | Root directory for normal file and command operations. |
| `LOCAL_SHELL_MCP_AUTH_MODE` | `--auth-mode` | `oauth` | Authentication mode: `oauth` or `none`. Do not expose public services with `none`. |
| `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | — | `true` | Allow localhost requests without bearer auth. |
| `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | — | `false` | Require auth for MCP initialize/list-tools discovery calls. |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `--public-base-url` | unset | Public HTTPS origin used in OAuth metadata. |
| `LOCAL_SHELL_MCP_OAUTH_ISSUER` | — | unset | Override OAuth issuer metadata. Defaults to public base URL when unset. |
| `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | — | unset | Override OAuth resource metadata. Defaults to public base URL when unset. |
| `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `--oauth-admin-pin` | unset | PIN required to approve OAuth authorization. |
| `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | `--oauth-jwt-secret` | `dev-change-me` | Secret used to sign bearer tokens. Set a strong random value for public OAuth deployments. |
| `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | — | `0` | Bearer token lifetime in seconds. `0` means no expiry. |
| `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | — | `300` | OAuth authorization-code lifetime in seconds. |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `--allow-full-container` / `--no-allow-full-container` | `false` | Disable built-in workspace and command restrictions. Use only in disposable containers or VMs. |
| `LOCAL_SHELL_MCP_ALLOW_NETWORK` | — | `true` | Allow network-capable operations. |
| `LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S` | — | `60` | Default shell command timeout. |
| `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | — | `3600` | Maximum shell command timeout. |
| `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | — | `200000` | Command output truncation limit. |
| `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | — | `512000` | Per-file read limit. |
| `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | — | `5000000` | Per-file write/edit limit. |
| `LOCAL_SHELL_MCP_MAX_GREP_RESULTS` | — | `200` | Maximum grep result count. |
| `LOCAL_SHELL_MCP_MAX_DIRECTORY_ENTRIES` | — | `5000` | Maximum listed directory entries. |
| `LOCAL_SHELL_MCP_MAX_GLOB_RESULTS` | — | `5000` | Maximum glob search results. |
| `LOCAL_SHELL_MCP_MAX_TREE_ENTRIES` | — | `5000` | Maximum tree-view entries. |
| `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | — | `100` | Maximum files read by a multi-file read operation. |
| `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | — | `5000000` | Combined byte limit for multi-file reads. |
| `LOCAL_SHELL_MCP_MAX_TODOS` | — | `1000` | Todo-list item limit. |
| `LOCAL_SHELL_MCP_MAX_TODO_BYTES` | — | `1000000` | Todo-list serialized byte limit. |
| `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | — | `1000000` | Audit-tail response byte limit. |
| `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | — | `20000000` | Audit-log rotation threshold. |
| `LOCAL_SHELL_MCP_MAX_TMP_FILES` | — | `500` | Temporary-file count limit. |
| `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | — | `50000000` | Temporary-file byte limit. |
| `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | — | `4` | Concurrent command limit. |
| `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | — | `16` | Persistent shell session limit. |
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `--remote` / `--no-remote` | `true` | Enable remote worker routes and tools. |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | — | `600` | One-time remote worker invite lifetime. |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | — | `25` | Remote worker long-poll heartbeat timeout. |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | — | `3600` | Control-side remote job result timeout. |
| `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | — | `true` | Enable agent capability bridge tools. |
| `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `--agent-config-dir` | `/home/agent/local-shell-mcp-config` | Read-only capability config directory. |
| `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | — | `5` | Agent MCP server probe timeout. |
| `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | — | `60` | Agent MCP tool-call timeout. |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | — | `true` | Register dynamic MCP bridge tools. |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS` | — | `true` | Register dynamic skill bridge tools. |
| `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | — | `/bin/bash` | Shell executable used for shell commands. |
| `LOCAL_SHELL_MCP_TMUX_BIN` | — | `tmux` | `tmux` executable. |
| `LOCAL_SHELL_MCP_RG_BIN` | — | `rg` | ripgrep executable. |
| `LOCAL_SHELL_MCP_GIT_BIN` | — | `git` | Git executable. |
| `LOCAL_SHELL_MCP_PYTHON_BIN` | — | `python3` | Python executable. |
| `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | — | built-in list | Comma-separated command denylist. Cleared when full-container mode is enabled. |
| `LOCAL_SHELL_MCP_PATH_DENYLIST` | — | built-in list | Comma-separated path denylist. Cleared when full-container mode is enabled. |

## Docker entrypoint settings

These variables are consumed by `scripts/docker-entrypoint.sh` before `local-shell-mcp` starts. They are intentionally not part of `Settings`, do not participate in application config-file precedence, and affect only Docker image startup behavior. In Docker Compose deployments, they are supplied from `.env` together with the application variables because `docker-compose.yml` uses `env_file: .env` for the main container.

| Environment variable | Default | Description |
|---|---:|---|
| `DOCKER_RUN_AS_ROOT` | `false` | Run the server process as root instead of the `agent` user. Prefer explicit `sudo` inside commands. |
| `DOCKER_PERSISTENT_CREDENTIALS` | `true` | Persist common developer credential files into `DOCKER_CREDENTIALS_DIR`. |
| `DOCKER_CREDENTIALS_DIR` | `/persist/credentials` | Root directory for persisted GitHub CLI, Git, SSH, `.netrc`, and GPG state. |
| `DOCKER_CHOWN_WORKSPACE` | `true` | `chown` the workspace to `agent` before starting the server. |

## Third-party and script variables

| Environment variable | Used by | Description |
|---|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | `docker-compose.yml` tunnel profile | Token for the optional Cloudflare Tunnel sidecar. |
| `TUNNEL_HOSTNAME` | `scripts/run-with-cloudflare-tunnel.sh` | Hostname passed to `cloudflared tunnel --hostname`. |
| `LOCAL_SHELL_MCP_CF_ACCESS_TEAM_DOMAIN` | `scripts/run-with-cloudflare-tunnel.sh` | Legacy Cloudflare Access script input. Not consumed by the application. |
| `LOCAL_SHELL_MCP_CF_ACCESS_AUDIENCE` | `scripts/run-with-cloudflare-tunnel.sh` | Legacy Cloudflare Access script input. Not consumed by the application. |
| `SSH_AUTH_SOCK` | optional Docker Compose mount | SSH agent socket to expose to the container instead of mounting private keys. |
