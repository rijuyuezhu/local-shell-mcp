# Tools

`local-shell-mcp` exposes a small read-only connector surface plus a full coding-agent surface. Tool availability depends on the MCP client and server configuration.

Regular ChatGPT connectors and Deep Research-style clients can use `search` and `fetch`. ChatGPT Developer Mode and full MCP clients can use the complete tool set.

All normal tools operate under `LOCAL_SHELL_MCP_WORKSPACE_ROOT` unless full-container mode is enabled. Remote tools perform the same category of operation on a connected remote worker and add a required `machine` argument.

## Read-only connector tools

| Tool | Purpose |
|---|---|
| `search` | Search workspace files and return connector-compatible result cards. |
| `fetch` | Fetch a workspace file by id returned from `search`. |

## Environment and audit

| Tool | Purpose |
|---|---|
| `environment_info` | Return workspace, auth, policy, and basic runtime information. |
| `audit_tail` | Read recent audit log entries. |
| `secret_scan` | Scan workspace text files for common secret patterns before commit or push. |

## Shell and Python

| Tool | Purpose |
|---|---|
| `run_shell_tool` | Run a bounded shell command in the workspace. |
| `run_python_tool` | Write Python code to a temporary file and execute it. |
| `shell_start` | Start a persistent tmux-backed shell session. |
| `shell_send` | Send input to a persistent shell session. |
| `shell_read` | Read recent output from a persistent shell session. |
| `shell_kill` | Kill a persistent shell session. |
| `shell_list` | List persistent shell sessions. |

Command execution is limited by timeout, output-size, and concurrency settings. Public shell calls use a stricter public timeout cap than the internal maximum. Persistent shells are useful for long-running REPLs, dev servers, and interactive commands.

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
| `apply_patch` | Apply a unified diff using `git apply`. |

The file tools reject path escapes outside the workspace unless `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`. Text reads and writes are bounded by configured byte limits. Binary files are not returned as text unless an explicit preview mode is requested.

## Git

| Tool | Purpose |
|---|---|
| `git_clone_tool` | Clone a Git repository. |
| `git_status_tool` | Run status and show remotes. |
| `git_diff_tool` | Show unstaged or staged diffs, optionally for one path or as stats. |
| `git_log_tool` | Show recent commits. |
| `git_checkout_tool` | Checkout a ref or create a branch. |
| `git_fetch_tool` | Fetch a remote, with pruning enabled by default. |
| `git_pull_tool` | Pull the current branch, fast-forward only by default. |
| `git_add_tool` | Stage paths. |
| `git_commit_tool` | Create a commit. |
| `git_push_tool` | Push current HEAD to a remote branch. |
| `git_show_tool` | Show a commit, object, or file at `ref:path`. |
| `git_reset_tool` | Reset with soft, mixed, or hard mode. |

Run `secret_scan` and inspect diffs before committing or pushing.

## Todo state

| Tool | Purpose |
|---|---|
| `todo_read_tool` | Read the agent todo list. |
| `todo_write_tool` | Replace the agent todo list. |

Todo state is stored under the server state directory and is bounded by configured count and byte limits.

## Remote worker management

| Tool | Purpose |
|---|---|
| `remote_invite` | Create a one-time command for a remote machine to join this control server. |
| `remote_list_machines` | List connected remote workers. |
| `remote_revoke_machine` | Revoke and remove a remote worker. |
| `remote_rename_machine` | Rename a remote worker. |
| `remote_environment_info` | Return environment information for a remote worker. |

Remote workers connect back to the control server over outbound HTTP(S), long-poll for jobs, execute them locally, and return results.

## Remote shell and Python

| Tool | Purpose |
|---|---|
| `remote_run_shell_tool` | Run a shell command on a remote worker. |
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

## Remote Git

| Tool | Purpose |
|---|---|
| `remote_git_clone_tool` | Clone a Git repository on a remote worker. |
| `remote_git_status_tool` | Run remote Git status and show remotes. |
| `remote_git_diff_tool` | Show remote diffs. |
| `remote_git_log_tool` | Show recent remote commits. |
| `remote_git_checkout_tool` | Checkout a remote ref or create a branch. |
| `remote_git_fetch_tool` | Fetch a remote repository. |
| `remote_git_pull_tool` | Pull a remote repository. |
| `remote_git_add_tool` | Stage remote paths. |
| `remote_git_commit_tool` | Create a remote commit. |
| `remote_git_push_tool` | Push remote HEAD. |
| `remote_git_show_tool` | Show a remote commit, object, or file. |
| `remote_git_reset_tool` | Reset a remote repository. |

## Agent capability bridge tools

These tools are registered when `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED=true`.

| Tool | Purpose |
|---|---|
| `agent_config_status` | Show loaded agent bridge config, discovered skills, MCP servers, and probe status with secrets redacted. |
| `activate_agent_skill` | Return the contents of a discovered `SKILL.md`. |
| `call_agent_mcp_tool` | Call a tool from a configured external MCP server through a fixed bridge. |

If dynamic tools are enabled in both environment settings and the bridge manifest, discovered skills and external MCP tools can also appear as individual MCP tools. Dynamic tools are hot-reloaded when the manifest changes.

## Safety-related behavior

- Path operations are restricted to the workspace by default.
- Default path denylists block sensitive fragments such as `.env`, credentials, private SSH keys, and `.git/config`.
- Default command denylists block host-control fragments such as Docker socket access, mounting, shutdown, reboot, firewall manipulation, and similar commands.
- `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` disables built-in path and command restrictions and adds auto-approval hints for command-capable tools. Use it only in disposable containers or VMs.
- OAuth metadata allows unauthenticated discovery by default for ChatGPT compatibility, while protected tool calls require OAuth unless localhost bypass or auth-free mode is configured.
