# Example prompts

Use these prompts as starting points when ChatGPT or another MCP client is connected to `local-shell-mcp`.

## Clone and inspect a repo

```text
Use local-shell-mcp. Clone https://github.com/fwerkor/FrameDiff.git into /workspace/FrameDiff, inspect the tree, search for fullnet, and report the main entry points.
```

## Make a change safely

```text
Use local-shell-mcp. Start a session in /workspace/FrameDiff, create a new branch ai/example-change with `bash(session_id=...)`, inspect the target files with `read` or `search`, make the requested code edit with `edit_lines` or `apply_patch(session_id=...)`, run relevant tests with `bash(session_id=...)`, run `secret_scan(session_id=...)`, show git diff --stat, commit, and push the branch.
```

## One-command remote worker onboarding

```text
Use local-shell-mcp. Create a remote worker invite with `remote_admin(action="invite", args={"name": "npu-4card", "workdir": "/home/cyh/FrameDiff"})`. Show me only the pasteable join command and then, after I say it has run, call `remote_admin(action="list", args={})` to confirm it is online.
```

## Remote machine diagnostics

```text
Use local-shell-mcp. Start a local session for the project, inspect the workspace, and run the relevant verification commands with `bash` using the returned session_id.
```

## Remote code edit and test

```text
Use local-shell-mcp. Start a session for the target project, search for the requested symbol with `search`, edit with `edit_lines`, run the relevant test with `bash`, then show git diff --stat with `bash`, always passing the returned session_id.
```
