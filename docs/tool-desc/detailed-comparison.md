# Tool-surface comparison after simplification

This document supersedes the earlier exploratory comparison. The current local-shell-mcp branch intentionally moves closer to opencode's smaller coding-agent surface by removing dedicated git porcelain tools and making the remaining MCP descriptions more operationally explicit.

## Current counts

| Project | Built-in tools counted | Notes |
| --- | ---: | --- |
| opencode | 12 | Core tools registered with `Tool.make`: `apply_patch`, `bash`, `edit`, `glob`, `grep`, `question`, `read`, `skill`, `todowrite`, `webfetch`, `websearch`, `write`. |
| local-shell-mcp | 47 | Built-in MCP tools returned by `build_mcp().list_tools()`; dynamic agent-bridge tools are not included in this static table. |

## What changed in local-shell-mcp

- Removed all dedicated local git tools: `git_clone_tool`, `git_status_tool`, `git_diff_tool`, `git_log_tool`, `git_checkout_tool`, `git_fetch_tool`, `git_pull_tool`, `git_add_tool`, `git_commit_tool`, `git_push_tool`, `git_show_tool`, and `git_reset_tool`.
- Removed all dedicated remote git mirror tools: `remote_git_*`.
- Removed `audit_tail` and `max_audit_tail_bytes`; audit logging remains internal.
- Removed git-specific configuration/scope entries: `git_bin` and `git:write`.
- Kept `apply_patch` because it is a file editing primitive. It happens to use `git apply` as a patch engine, but normal git workflows should now go through shell tools.
- Expanded MCP descriptions for remaining tools with usage guidance, parameter defaults, runtime limits, path semantics, and tool-choice advice.
- Added server-level MCP instructions, modeled after opencode-style initial agent prompts, covering communication, autonomy, codebase workflow, shell/git/remote usage, validation, safety, and review mode.

## Why local-shell-mcp still has more tools than opencode

local-shell-mcp is an MCP control surface for a workspace/container plus optional remote workers. It still exposes capabilities that opencode keeps outside its compact core surface:

- remote worker enrollment and remote execution tools;
- persistent shell sessions;
- explicit Python script execution;
- connector-style workspace `search`/`fetch`;
- bounded file/search helpers;
- a retained heuristic `secret_scan` helper.

The intended model behavior is now closer to opencode for git: use shell commands rather than a wide set of dedicated git tools.

## Remaining local-shell-mcp surface

| Group | Count | Tools |
| --- | --- | --- |
| environment | 1 | environment_info |
| filesystem | 12 | apply_patch, delete_file_or_dir, edit_file, glob_search, grep_search, list_files, multi_edit_file, read_file, read_many_files, secret_scan, tree_view, write_file |
| remote | 23 | remote_apply_patch, remote_delete_file_or_dir, remote_edit_file, remote_environment_info, remote_glob_search, remote_grep_search, remote_invite, remote_list_files, remote_list_machines, remote_multi_edit_file, remote_read_file, remote_read_many_files, remote_rename_machine, remote_revoke_machine, remote_run_python_tool, remote_run_shell_tool, remote_shell_kill, remote_shell_list, remote_shell_read, remote_shell_send, remote_shell_start, remote_tree_view, remote_write_file |
| shell | 7 | run_python_tool, run_shell_tool, shell_kill, shell_list, shell_read, shell_send, shell_start |
| todo | 2 | todo_read_tool, todo_write_tool |
| workspace | 2 | fetch, search |
