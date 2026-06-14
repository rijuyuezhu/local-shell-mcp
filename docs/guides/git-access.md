# Git access

`local-shell-mcp` does not expose dedicated Git tools. Use `run_shell_command` or a persistent shell for Git workflows.

## Recommended credential approach

Prefer narrowly scoped credentials:

- Single-repository deploy keys.
- Short-lived GitHub App installation tokens.
- A dedicated machine user with minimal repository access.
- Disposable credentials for disposable containers.

Avoid mounting unrestricted SSH keys or all of `~/.ssh` into the workspace.

## Docker credential persistence

Docker deployments can persist common credential locations across container rebuilds with:

```env
DOCKER_PERSISTENT_CREDENTIALS=true
DOCKER_CREDENTIALS_DIR=/persist/credentials
```

The Compose setup stores this under the `local-shell-mcp-credentials` volume.

Set `DOCKER_PERSISTENT_CREDENTIALS=false` for more disposable authentication state.

## Typical prompts

Inspect the current Git state:

```text
Use local-shell-mcp to run git status --short and summarize the branch, remotes, and uncommitted changes.
```

Review changes before commit:

```text
Use local-shell-mcp to show git diff --stat, summarize the important changes, and run secret_scan before I commit.
```

Create a patch-based edit:

```text
Use local-shell-mcp to make the smallest safe code change. Prefer apply_patch for multi-file edits, then show git diff --stat.
```

## Safety checklist

Before commit or push:

1. Review `git status --short`.
2. Review `git diff` or `git diff --stat`.
3. Run the relevant tests.
4. Run `secret_scan`.
5. Confirm that no generated credential, audit, cache, or local state files are staged.
