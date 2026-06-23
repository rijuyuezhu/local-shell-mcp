# Stateful session tool surface redesign plan

This document is the single source of truth for continuing the stateful session redesign on branch `feat/agent-tool-surface` in `/workspace/local-shell-mcp-tool-compare`.

When a new AI context continues this task, start by reading this file, then inspect the current git diff/status. Do not rely on chat history. Do not touch `/workspace/local-shell-mcp`; that worktree may contain user changes.

## Goal

Replace the remaining stateless/default-session workflow with an explicit stateful session workflow.

The model-facing workflow should become:

1. `session_start(...)` allocates an 8-character alphanumeric `session_id` bound to a local or remote workspace.
2. Normal coding tools receive `session_id` and operate inside that session's bound workspace.
3. For remote sessions, normal tools automatically dispatch to the paired remote worker session; the model does not call a generic `remote(...)` wrapper.
4. Persistent shell handles are renamed to `shell_id` so they are not confused with agent/workspace `session_id`.

## Accepted design decisions

### Session identity

- Agent/workspace session ids are 8-character alphanumeric strings: `[A-Za-z0-9]{8}`.
- Generate ids with `secrets`, retry on collision, and keep them opaque. Do not encode local/remote in the id.
- `session_id` refers to the agent/workspace session in normal tools.
- Persistent shell handles must be called `shell_id`, not `session_id`, in model-facing schemas, docs, and result descriptions.

### Session records

A session record should include at least:

- `session_id`
- `target`: `local` or `remote`
- `workdir`: canonical local workdir or remote worker workdir
- `machine`: remote worker name for remote sessions, otherwise `null`
- `worker_session_id`: paired worker-side session id for remote sessions, otherwise `null`
- timestamps: `created_at`, `updated_at`, optional `expires_at`
- optional `label`
- optional principal/auth metadata if cheaply available

Session state should own grounding snapshots. Snapshot lookup must be keyed by `session_id`; the current process-global `default` fallback should be removed from normal paths.

### Workdir binding

`session_start` stores `workdir`. Relative paths and default command cwd should resolve inside the session workdir.

This is intentional because later project-level initialization can traverse from the session workdir to discover files such as:

- `AGENTS.md`
- `CLAUDE.md`
- `CONTRIBUTING*`
- local-shell-mcp project config
- repo root / git metadata

First implementation should store workdir and may return lightweight discovery metadata, but should avoid dumping large instruction files in the `session_start` response.

### Initialization tool

Remove the read-only `environment_info` tool from the default/model-facing surface. Replace initialization guidance with `session_start`.

`session_start` should return enough orientation data for the model to begin work, for example:

- `session_id`
- `target`
- `workdir`
- workspace/repo summary where cheap
- discovered instruction file paths where cheap
- message telling the model to pass `session_id` to subsequent workspace tools

`environment_info` can be removed outright from the agent-facing surface. If internals/tests still need an environment probe, keep that as a private op/helper or non-default diagnostic, not as the primary model-facing initialization tool.

### Remote sessions

Remote work should be session-based instead of `remote(machine, op, args)` based.

`session_start(target="remote", machine="gpu1", workdir="/path")` should:

1. verify the worker exists/is reachable;
2. call the worker-side `session_start(target="local", workdir="/path")` or equivalent worker op;
3. store a control-server session record with `target="remote"`, `machine`, `workdir`, and `worker_session_id`;
4. return only the control-server `session_id` to the model.

After this, normal tools dispatch by session:

- `read(session_id=remote_session, path="src/foo.py")` -> remote worker read using `worker_session_id`
- `search(session_id=remote_session, ...)` -> remote worker search
- `edit_lines(session_id=remote_session, ...)` -> remote worker edit_lines
- `bash(session_id=remote_session, ...)` -> remote worker bash
- `job(session_id=remote_session, ...)` -> remote worker job

The generic `remote(...)` tool should be deleted from the model-facing surface. Do not keep it as a recommended escape hatch. Keep `remote_admin(...)` or equivalent control-plane actions for invite/list/revoke/rename unless/until a separate admin-session design replaces it.

### Tool parameter policy

Stateful/workspace-affecting tools should require `session_id`.

Required session tools should include at least:

- `read`
- `search`
- `edit_lines`
- `bash`
- `job`
- `write_file`
- `delete_file_or_dir`
- `apply_patch`
- todos if they remain session-scoped
- remote-session-dispatched equivalents of the above

Pure metadata/config tools may remain sessionless only if they do not read or mutate workspace/session state.

### Registry/dispatch architecture

Avoid scattering ad hoc local-vs-remote dispatch logic through every tool registry.

Preferred layering:

- session store: create/require/touch/end sessions and hold snapshot metadata;
- typed local ops: perform local read/search/edit/bash/job/etc against a resolved session workdir;
- session dispatch helpers: decide whether a session is local or remote and call the correct local op or remote worker tool;
- registry layer: validate model-facing arguments and call the dispatch/helper layer.

Consider adding declarative metadata such as `requires_session=True` on `ToolDefinition` so required `session_id` validation is centralized and covered by surface tests.

## Planned implementation slices

### Slice 1: Plan and guardrails

- [x] Create this stateful plan document.
- [ ] Confirm final plan with the user.
- [ ] Keep this file updated after each implementation slice.

### Slice 2: Session model and store

- [ ] Replace the current snapshot-only/default session workaround with first-class session records.
- [ ] Add 8-character alphanumeric session id generation with collision retry.
- [ ] Add `create_session`, `require_session`, `touch_session`, `end_session`, and test helpers.
- [ ] Store `workdir`, target, optional machine, optional worker session id, timestamps, and optional label.
- [ ] Remove normal-path fallback to `DEFAULT_TOOL_SESSION_ID`.
- [ ] Add unit tests for id format, uniqueness retry, missing session errors, workdir storage, and snapshot isolation.

### Slice 3: `session_start` tool

- [ ] Add input/result models for `session_start`.
- [ ] Add model-facing `session_start(target="local", workdir=".", machine=None, label=None)`.
- [ ] Return `session_id`, target, workdir, and lightweight orientation/discovery metadata.
- [ ] Remove `environment_info` from the default/model-facing surface.
- [ ] Update MCP server instructions to start substantial workspace work with `session_start`.
- [ ] Update docs and generated references.
- [ ] Add tests proving `environment_info` is absent from the default MCP surface and `session_start` is present.

### Slice 4: Local session-bound read/search/edit

- [ ] Make `read`, `search`, and `edit_lines` require `session_id`.
- [ ] Resolve relative paths against the session workdir.
- [ ] Ensure read/search snapshots are recorded under the explicit session.
- [ ] Ensure `edit_lines` rejects missing session, unknown snapshot, cross-session snapshot, stale snapshot, and unseen ranges.
- [ ] Update docs/generated references/tests.

### Slice 5: Local session-bound bash/job

- [ ] Make `bash` require `session_id` and default cwd to the session workdir.
- [ ] Bind tracked jobs to `session_id` in the job store.
- [ ] Make `job` require `session_id` and list/poll/cancel/retry only jobs in that session.
- [ ] Ensure job ids remain stable and job output does not expose shell internals unnecessarily.
- [ ] Update tests for cross-session job isolation.

### Slice 6: Rename persistent shell handle to `shell_id`

- [ ] Rename model-facing persistent shell parameters from `session_id` to `shell_id` for local shell companion tools.
- [ ] Rename model-facing persistent remote shell parameters from `session_id` to `shell_id` for remote/worker internals that remain exposed.
- [ ] Update result models to return `shell_id`; optionally include legacy `session_id` internally only where needed for compatibility tests.
- [ ] Update descriptions, docs, generated references, and tests.
- [ ] Add surface tests preventing persistent shell descriptions from calling shell handles agent `session_id`.

### Slice 7: Remote session start and dispatch

- [ ] Extend `session_start` with `target="remote"`, required `machine`, and remote `workdir`.
- [ ] On remote start, create a worker-side local session and store `worker_session_id` in the control-server session record.
- [ ] Dispatch `read/search/edit_lines/bash/job` through the session record when `target="remote"`.
- [ ] Propagate the worker session id to worker-side tools.
- [ ] Add tests for remote session creation, remote read/search/edit/bash/job dispatch, and missing/offline worker errors.

### Slice 8: Delete generic `remote(...)`

- [ ] Remove the generic `remote(machine, op, args)` model-facing tool.
- [ ] Remove `remote` from generated references and server instructions.
- [ ] Keep or adjust `remote_admin(...)` for control-plane invite/list/revoke/rename.
- [ ] Ensure no model-facing docs recommend `remote(...)`.
- [ ] Add surface tests proving `remote` is absent and remote work uses `session_start(target="remote")` plus normal tools.

### Slice 9: Remaining stateful tools and docs

- [ ] Decide session policy for `write_file`, `delete_file_or_dir`, `apply_patch`, todos, file links, secret scan, and connector-style search/fetch.
- [ ] Make workspace-affecting tools session-bound where appropriate.
- [ ] Update user docs, examples, troubleshooting, generated references, and PR body.
- [ ] Run full validation and update this document with final status.

## Current TODO

Next implementation task:

1. Confirm this plan with the user.
2. Implement Slice 2 and Slice 3 first: first-class local sessions plus `session_start`, and remove `environment_info` from the default/model-facing surface.
3. Keep this document updated after each slice, including completed checkboxes, changed design decisions, validation commands, and known risks.

## Validation checklist

Run focused checks after each slice, then broader checks before commit/push:

```bash
uv run ruff check src tests
uv run pyright
uv run pytest tests/test_tool_surface.py tests/test_mcp_chatgpt_compat.py tests/test_export_tools_json.py -q
uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json
pre-commit run --all-files
git diff --check
```

For remote/session-dispatch slices, also run relevant remote tests, including:

```bash
uv run pytest tests/test_remote_facade.py tests/test_e2e_remote_worker.py -q
```

Before reporting completion of an implementation slice, inspect the live MCP surface with `build_mcp().list_tools()` and confirm expected additions/removals.

## Known risks and open questions

- How much legacy compatibility to keep for HTTP routes is undecided; model-facing MCP surface should still remove `environment_info` and generic `remote(...)`.
- Renaming persistent shell handles from `session_id` to `shell_id` may require compatibility shims or coordinated test updates.
- Remote paired session lifecycle needs careful cleanup if the control server session ends while the worker remains online, or if the worker restarts.
- Session persistence across server restarts is undecided. Initial implementation may be process-local, but the design should not preclude persisted sessions later.
- Project instruction discovery should be lightweight initially to avoid making `session_start` slow or noisy.
