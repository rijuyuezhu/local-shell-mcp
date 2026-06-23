# Example prompts

Use these prompts as starting points when ChatGPT or another MCP client is connected to `local-shell-mcp`.

## Clone and inspect a repo

```text
Use local-shell-mcp. Clone https://github.com/fwerkor/FrameDiff.git into /workspace/FrameDiff, inspect the tree, search for fullnet, and report the main entry points.
```

## Make a change safely

```text
Use local-shell-mcp. In /workspace/FrameDiff, create a new branch ai/example-change, make the requested code edit with edit_file or apply_patch, run relevant tests, show git diff --stat, run secret_scan, commit, and push the branch.
```

## One-command remote worker onboarding

```text
Use local-shell-mcp. Create a remote worker invite named npu-4card with workdir /home/cyh/FrameDiff. Show me only the pasteable join command and then, after I say it has run, call remote_list_machines to confirm it is online.
```

## Remote machine diagnostics

```text
Use local-shell-mcp. On remote machine npu-4card, run pwd, hostname, python3 --version, git log -1 --oneline, and npu-smi info from /home/cyh/FrameDiff. Use `remote(machine, op="bash", args={...})`.
```

## Remote code edit and test

```text
Use local-shell-mcp. On remote machine hpc-a, inspect /home/cyh/project, search for the requested symbol with `remote(op="search")`, edit with `remote(op="edit_lines")` or `remote(op="apply_patch")`, run the relevant test with `remote(op="bash")`, then show git diff --stat with `remote(op="bash")`.
```
