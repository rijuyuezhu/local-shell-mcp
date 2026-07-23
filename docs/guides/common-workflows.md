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

For code changes, start with `session_start(workdir=...)`, then pass the returned `session_id` to session-bound tools. Use `read` for file or directory context, `search(pattern, paths=...)` for content discovery, `hashline_edit` as the default edit tool for existing files, `write_file` for new files or intentional whole-file replacement, and `bash(session_id=...)` for terminal work such as tests, builds, package managers, git inspection, and scripts. Prefer `read` selectors such as `src/foo.py:50-80`, `src/foo.py:50+20`, and `src/foo.py:raw`; hashline output and search snippets carry `[path#snapshot_id]` plus `line:text` rows. Copy those rows into `hashline_edit`, write only `+` final-content rows, keep ranges tight, and re-read after each successful edit or stale/surprising result. Use `edit_lines` only when exact structured path/start/end/replacement arguments are already available. The intended default surface should stay small and semantic. Use `apply_patch(session_id=..., patch=..., cwd=...)` when a caller already has a portable unified diff or an `*** Begin Patch` compatibility envelope spanning one or more files. The tool validates the complete envelope, resolves paths inside the explicit session workdir, runs `git apply --check`, and invokes Git through native argument vectors before applying; it is not a replacement for grounded `hashline_edit` during ordinary model-driven editing.


### Session environment orientation

Both `session_start` and `session_change_cwd` return the same nested `environment` object. Use it before choosing a tool instead of assuming that Git, tmux, Chromium, Bun, Playwright, OpenTUI, ConPTY, remote workers, HTTP transfer, or Agent Bridge OAuth are available. The groups are:

- `runtime`: local-shell-mcp and Python versions, source/frozen runtime, normalized OS release, architecture, and process width;
- `workspace`: the canonical target workspace/workdir, local or remote target, configured machine name, and normalized remote-worker runtime/service identity;
- `tools`: bounded allowlisted probes with `available`, `status`, extracted `version`, and a safe source category;
- `capabilities`: effective raw terminal, browser UI, OpenTUI, remote-worker, Agent Bridge/OAuth, transfer, and audit support;
- `policy`: safe limits and modes that affect tool choice, including timeouts, output/file/request budgets, concurrency, transfer limits, and full-control state.

Probe status is one of `available`, `missing`, `timeout`, `error`, or `unsupported`. A timeout/error does not expose raw stderr or exception text and does not mark the tool available. Probes run concurrently with independent bounds and are briefly cached; `session_change_cwd` still recomputes workspace, Git, instruction-file, capability, and policy orientation. The response never contains environment-variable values, OAuth tokens, admin PINs, command/path denylists, state/config paths, full executable paths, or worker runtime digests. There is intentionally no separate `environment_info` tool.

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

## Inspect images natively

Use `view_image(session_id=..., path=...)` for PNG, JPEG, GIF, and WebP files inside an explicit local or remote session. The tool is MCP-only because it returns native image content rather than embedding large base64 payloads in the REST surface. Images are bounded by `max_view_image_bytes` (20 MiB by default); remote images are read through the existing validated transfer-chunk protocol.

```text
Use local-shell-mcp. Start a session for this project, then view artifacts/plot.png with view_image using that session_id and explain the visual result.
```

## Share an artifact through a browser link

Use `create_file_link` only after starting an explicit local or remote session. The returned URL is a bearer secret and serves an immutable creation-time snapshot, so later edits to the source do not change what the URL returns. Browser download is the default:

```text
Use local-shell-mcp. Start a session for the project, create a file link for artifacts/report.pdf with max_downloads=1, and show me the URL without exposing the token anywhere else.
```

Set `inline=true` only when in-browser rendering is necessary, such as previewing an image or PDF. Inline responses are sandboxed, but the snapshot and URL must still be treated as sensitive until expiry or revocation.

## Copy files or directories between sessions

Start both source and destination sessions, then use `session_copy` with their explicit IDs. This works across local workspaces, local-to-remote, remote-to-local, and different remote workers:

```text
Use local-shell-mcp. Start one session for the source workspace and one for the destination workspace. Copy artifacts/checkpoint.bin between them with session_copy, keep overwrite=false, and verify the destination hash after completion.
```

For directories, `session_copy` validates and extracts into staging before replacing the destination. A cancellation aborts the active file write and cleans both archive scratch paths. Use `kind="file"` or `kind="dir"` when auto-detection would be ambiguous.

The default remains synchronous. For a long transfer, set `background=true`; the tool returns immediately with a managed `job_id` owned by `src_session_id`:

```text
Use local-shell-mcp. Copy artifacts/checkpoint.bin between these two sessions with session_copy(background=true). Poll the returned job using the source session_id, report progress, and verify the structured result when it succeeds.
```

`job(poll=[...])` exposes bounded log output plus structured phases such as `preparing`, `packing`, `transferring`, `unpacking`, and `completed`. The successful job `result` is the same structured `SessionCopyOutput` returned by synchronous mode. `job(cancel=[...])` cancels the controller task and runs the existing transactional abort cleanup. `job(retry=[...])` starts a fresh transfer attempt from the durable source/destination payload rather than reusing an old transfer capability or partially committed destination. Managed payloads, progress, and results are each capped at 256 KiB, logs remain subject to `max_job_log_bytes`, and byte progress is persisted at most twice per second except at phase boundaries and completion.

Remote-session job snapshots merge shell jobs running on the worker with controller-managed copy jobs. A controller-managed copy remains inspectable and cancellable if the worker becomes temporarily unavailable. If the controller process loses a live managed task, the record becomes `lost`; retry is available while the owning sessions and source path still exist.

## Work with long-running commands

Use `bash(session_id=...)` for terminal work. By default it runs bounded one-shot commands in the session workdir; set `async_=true` for tracked long-running non-interactive shell work. The same `job(session_id=...)` companion manages both shell jobs and controller-managed transfer jobs. Shell jobs persist exit status and bounded output under `state_dir`, so polling continues after command exit or server restart. Managed jobs persist their payload, progress, result, and bounded log, but their live task is process-local; a missing task is marked `lost` instead of being reported as still running. `max_job_log_bytes` limits retained output per attempt, while `max_jobs` bounds retained terminal records without pruning active jobs.

Set `pty=true` for dev servers, REPLs, and interactive processes:

```text
Use local-shell-mcp. Start a session for this project. Then run bash with pty=true using that agent session_id. Use the returned shell_id to read output and tell me the local URL.
```

When done:

```text
Use local-shell-mcp to list persistent shells and kill the development server shell by shell_id. For async bash jobs or background session copies, use job with the owning agent session to poll, cancel, or retry them.
```

## Debug tool behavior

Watch the audit log from the host or container:

```bash
docker compose exec local-shell-mcp tail -f /workspace/.local-shell-mcp/audit_log/audit.jsonl
```

Each routed MCP or REST tool call should produce paired `tool_call_start` and `tool_call_end` records linked by `call_id`.
