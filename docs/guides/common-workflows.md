# Common workflows

These prompts assume ChatGPT or another MCP client is connected to `local-shell-mcp`.

## Inspect first, then change

Start most sessions by asking the model to inspect the workspace before editing:

```text
Use local-shell-mcp to inspect this repository, identify the project type, and summarize the likely check commands before making any changes.
```

Then ask for a plan:

```text
Use local-shell-mcp to propose a minimal implementation plan. Do not edit files until you have shown the files you expect to touch.
```

## Make a code change

```text
Use local-shell-mcp to implement this change. Keep the diff focused, run the relevant tests, and summarize the result with git diff highlights.
```

For code changes, start with `session_start(workdir=...)`, then pass the returned `session_id` to session-bound tools. Use `read` for file or directory context, `search(pattern, paths=...)` for content discovery, `hashline_edit` as the default edit tool for existing files, `write_file` for new files or intentional whole-file replacement, and `bash(session_id=...)` for terminal work such as tests, builds, package managers, git inspection, and scripts. Prefer `read` selectors such as `src/foo.py:50-80`, `src/foo.py:50+20`, and `src/foo.py:raw`; hashline output and search snippets carry `[path#snapshot_id]` plus `line:text` rows. Copy those rows into `hashline_edit`, write only `+` final-content rows, keep ranges tight, and re-read after each successful edit or stale/surprising result. Use `edit_lines` only when exact structured path/start/end/replacement arguments are already available. The intended default surface should stay small and semantic.

## Run tests and checks

```text
Use local-shell-mcp to run the repository's normal checks. If a check fails, identify whether it is caused by your change before editing anything else.
```

For this repository, contributor checks are documented in [Development](../development.md):

```bash
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
```

## Review before commit

```text
Use local-shell-mcp to show git status, summarize the diff, and run secret_scan before I commit.
```

`secret_scan` is heuristic. It does not prove the workspace is secret-free, but it is a useful final precaution before sharing a diff.

## Work with long-running commands

Use `bash(session_id=...)` for terminal work. By default it runs bounded one-shot commands in the session workdir; set `async_=true` for tracked long-running non-interactive work owned by that session, and manage it with `job(session_id=...)`. Set `pty=true` for dev servers, REPLs, and interactive processes:

```text
Use local-shell-mcp. Start a session for this project. Then run bash with pty=true using that agent session_id. Use the returned shell_id to read output and tell me the local URL.
```

When done:

```text
Use local-shell-mcp to list persistent shells and kill the development server shell by shell_id. For async bash jobs, use job with the same agent session to poll or cancel them.
```

## Debug tool behavior

Watch the audit log from the host or container:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit_log/audit.jsonl
```

Each routed MCP or REST tool call should produce paired `tool_call_start` and `tool_call_end` records linked by `call_id`.
