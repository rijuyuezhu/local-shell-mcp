# Tools reference

Tool availability depends on the MCP client and server configuration. Regular ChatGPT connectors and Deep Research-style clients can use `search` and `fetch`. ChatGPT Developer Mode and full MCP clients can use the complete tool set.

All normal tools operate under `LOCAL_SHELL_MCP_WORKSPACE_ROOT` unless full-container mode is enabled. Remote tools perform the same category of operation on a connected remote worker and add a required `machine` argument.

## Read-only connector tools

| Tool | Purpose |
|---|---|
| `search` | Search workspace files and return connector-compatible result cards. |
| `fetch` | Fetch a workspace file by id returned from `search`. |

## Environment and safety

| Tool | Purpose |
|---|---|
| `environment_info` | Return workspace, auth, policy, and basic runtime information. |
| `secret_scan` | Scan workspace text files for common secret patterns before commit, push, release, or sharing logs. |

## Shell and Python

| Tool | Purpose |
|---|---|
| `run_shell_tool` | Run a bounded non-interactive shell command in the workspace. Use this for Git workflows. |
| `run_python_tool` | Write Python code to a temporary file and execute it. |
| `shell_start` | Start a persistent tmux-backed shell session. |
| `shell_send` | Send input to a persistent shell session. |
| `shell_read` | Read recent output from a persistent shell session. |
| `shell_kill` | Kill a persistent shell session. |
| `shell_list` | List persistent shell sessions. |

## Filesystem and search

| Tool | Purpose |
|---|---|
| `list_files` | List files and directories. |
| `tree_view` | Return a compact directory tree. |
| `glob_search` | Find files by glob pattern. |
| `grep_search` | Search file contents with ripgrep. |
| `read_file` | Read a UTF-8 text file, optionally by line range. Binary preview must be requested explicitly. |
| `read_many_files` | Read several UTF-8 text files with shared range and binary-preview options. |
| `write_file` | Write a UTF-8 text file. |
| `edit_file` | Replace exact text in a file. |
| `multi_edit_file` | Apply multiple exact-text edits to one file. |
| `delete_file_or_dir` | Delete a file or directory. |
| `apply_patch` | Apply a unified diff using `git apply` as a file-editing primitive. |

## File download links

These tools create and manage tokenized browser-accessible links for files in the workspace. The management tools require the normal MCP/REST authentication; the generated `/download/{token}` URL is public but protected by a high-entropy token, TTL, optional download-count limit, optional size limit, and revocation.

| Tool | Purpose |
|---|---|
| `create_file_link` | Create a temporary download URL for a regular workspace file. |
| `list_file_links` | List active generated download URLs. |
| `revoke_file_link` | Revoke a generated download URL by token. |

## Todo state

| Tool | Purpose |
|---|---|
| `todo_read_tool` | Read the agent todo list. |
| `todo_write_tool` | Replace the agent todo list. |

## Remote worker management

| Tool | Purpose |
|---|---|
| `remote_invite` | Create a one-time command for a remote machine to join this control server. |
| `remote_list_machines` | List connected remote workers. |
| `remote_revoke_machine` | Revoke and remove a remote worker. |
| `remote_rename_machine` | Rename a remote worker. |
| `remote_environment_info` | Return environment information for a remote worker. |

## Remote shell and Python

| Tool | Purpose |
|---|---|
| `remote_run_shell_tool` | Run a shell command on a remote worker. Use this for remote Git workflows. |
| `remote_run_python_tool` | Write Python code to a temporary file and execute it on a remote worker. |
| `remote_shell_start` | Start a persistent remote shell session. |
| `remote_shell_send` | Send input to a remote shell session. |
| `remote_shell_read` | Read recent output from a remote shell session. |
| `remote_shell_kill` | Kill a remote shell session. |
| `remote_shell_list` | List remote shell sessions. |

## Remote filesystem and search

| Tool | Purpose |
|---|---|
| `remote_list_files` | List remote files and directories. |
| `remote_tree_view` | Return a compact remote directory tree. |
| `remote_glob_search` | Find remote files by glob pattern. |
| `remote_grep_search` | Search remote file contents with ripgrep. |
| `remote_read_file` | Read a remote UTF-8 text file, optionally by line range. |
| `remote_read_many_files` | Read several remote UTF-8 text files. |
| `remote_write_file` | Write a remote UTF-8 text file. |
| `remote_edit_file` | Replace exact text in a remote file. |
| `remote_multi_edit_file` | Apply multiple exact-text edits to one remote file. |
| `remote_delete_file_or_dir` | Delete a remote file or directory. |
| `remote_apply_patch` | Apply a unified diff on a remote worker. |

## Agent capability bridge tools

These tools are registered when `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED=true`.

| Tool | Purpose |
|---|---|
| `agent_config_status` | Show loaded agent bridge config, discovered skills, MCP servers, and probe status with secrets redacted. |
| `activate_agent_skill` | Return the contents of a discovered `SKILL.md`. |
| `call_agent_mcp_tool` | Call a tool from a configured external MCP server through a fixed bridge. |

## Safety-related behavior

- Path operations are restricted to the workspace by default.
- Default path denylists block sensitive fragments such as `.env`, credentials, private SSH keys, and `.git/config`.
- Default command denylists block host-control fragments such as Docker socket access, mounting, shutdown, reboot, firewall manipulation, and similar commands.
- Full-container mode disables built-in path and command restrictions and adds auto-approval hints for command-capable tools.
- OAuth/bootstrap metadata, health checks, and remote-worker join/poll/result endpoints are public. MCP-over-HTTP tool calls require OAuth unless `auth_mode=none` is configured.
