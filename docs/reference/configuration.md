# Configuration reference

`local-shell-mcp` can be configured with CLI arguments, environment variables, or an optional YAML config file.

## Precedence

Settings resolve in this order:

```text
defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments
```

Use:

- CLI arguments for one-off runs.
- `.env` and `LOCAL_SHELL_MCP_*` variables for Compose deployments.
- `config.example.yaml` when a file-based configuration is more convenient.

Docker image startup knobs use `DOCKER_*` variables because they are consumed by the container entrypoint before the application starts.

`audit_log_path` and `agent_config_dir` are not configurable settings. They are derived from `state_dir` as `audit_log/audit.jsonl` and `agent_config`.

## Common application settings

| Setting | CLI | Environment | Default |
|---|---|---|---:|
| Server mode | `--mode` | `LOCAL_SHELL_MCP_MODE` | `mcp` |
| Bind host | `--host` | `LOCAL_SHELL_MCP_HOST` | `0.0.0.0` |
| Bind port | `--port` | `LOCAL_SHELL_MCP_PORT` | `8765` |
| Workspace root | `--workspace-root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `/workspace` |
| State directory | `--state-dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `/workspace/.local-shell-mcp` |
| Auth mode | `--auth-mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `oauth` |
| Public OAuth origin | `--public-base-url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | unset |
| OAuth approval PIN | `--oauth-admin-pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | unset |
| Full-container mode | `--allow-full-container true/false` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `false` |
| Remote worker routes | `--remote-enabled true/false` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` |
| MCP request auth | `--require-auth-for-mcp-discovery true/false` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `true` |
| OAuth token TTL | advanced flag omitted from examples | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `3600` |

## Safety and resource limits

Important limits include:

| Environment | Meaning | Default |
|---|---|---:|
| `LOCAL_SHELL_MCP_PUBLIC_TOOL_TIMEOUT_S` | Public MCP/HTTP tool watchdog timeout | `60` |
| `LOCAL_SHELL_MCP_PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S` | Default public shell timeout | `10` |
| `LOCAL_SHELL_MCP_PUBLIC_RUN_SHELL_MAX_TIMEOUT_S` | Maximum public shell timeout | `60` |
| `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | Command output truncation limit | `200000` |
| `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | Per-file read limit | `512000` |
| `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | Per-file write/edit limit | `5000000` |
| `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | Concurrent command limit | `4` |
| `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | Persistent shell session limit | `16` |

## File download links

`create_file_link` can create public `/download/{token}` URLs for regular files in the workspace. The creation/list/revoke tools are authenticated like other tools, while the generated URL is intentionally public so browsers and MCP clients can fetch artifacts directly.

| Environment | Meaning | Default |
|---|---|---:|
| `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | Enable tokenized public download links created by protected tools | `true` |
| `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | Default generated-link lifetime in seconds | `3600` |
| `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | Maximum accepted generated-link lifetime in seconds | `604800` |
| `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | Default download-count limit; `0` means unlimited until expiry | `0` |
| `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | Maximum linked file size; `0` disables this size limit | `0` |

Set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` for public deployments so generated URLs use the externally reachable HTTPS origin instead of the bind host.

## Denylists

By default, command and path denylists block common high-risk operations and sensitive paths.

```env
LOCAL_SHELL_MCP_COMMAND_DENYLIST=docker.sock,/var/run/docker.sock,mkfs,mount,umount,shutdown,reboot,systemctl,iptables,nft
LOCAL_SHELL_MCP_PATH_DENYLIST=.ssh/id_rsa,.ssh/id_ed25519,.env,secrets,credentials,.git/config
```

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` clears built-in command and path restrictions. Use it only in disposable containers or VMs.

## Complete examples

The generated examples remain the source of truth for all settings:

- `.env.example` for Compose and environment-variable deployments.
- `config.example.yaml` for file-based configuration.

Regenerate and check them during development with:

```bash
uv run python scripts/generate-config-examples.py --check
```
