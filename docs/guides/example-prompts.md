# Example prompts

These prompts emphasize explicit workspaces, inspection before editing, and verification after changes. Adapt paths and commands to your project.

## Inspect a repository

```text
Use local-shell-mcp in /workspace/project. Inspect the repository tree, instruction files, and Git status. Summarize the main entry points and do not change files yet.
```

## Make a focused change

```text
Use local-shell-mcp in /workspace/project. Create a new branch, inspect the relevant code and tests, make the smallest requested change, run focused validation, show the final diff, and report anything not verified.
```

## Enroll a remote worker

```text
Use local-shell-mcp to create a one-time remote worker invite named gpu1 with workdir /home/me/project. Show me the command to run on that machine, then wait for me to confirm enrollment before checking its status.
```

## Inspect a remote machine

```text
Use local-shell-mcp on remote machine gpu1 in /home/me/project. Inspect the repository and environment, run git status, and report what is available before editing.
```

## Run a remote test

```text
Use local-shell-mcp on gpu1. Find the relevant test for the requested change, run it as a bounded or background job as appropriate, and summarize the result and log location.
```

## Copy an artifact

```text
Use local-shell-mcp to copy results/report.json from the gpu1 session into reports/latest.json in my local project, then verify the destination.
```

## Inspect a generated image

```text
Use local-shell-mcp in the project. Run the command that generates the plot, open the resulting image, describe any visual anomaly, and relate it to the generating code.
```

See [Common workflows](common-workflows.md) for the underlying workflow and [Tool reference](../reference/tools.md) for exact contracts.
