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

### Model-facing description policy

- Model-facing tool descriptions, generated references, and MCP server instructions must describe only currently available behavior. Do not mention future slices, later planned support, or implementation roadmap language there. Keep roadmap notes in this file only.

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
- [x] Keep this file updated after each implementation slice.

### Slice 2: Session model and store

- [x] Replace the current snapshot-only/default session workaround with first-class session records.
- [x] Add 8-character alphanumeric session id generation with collision retry.
- [x] Add `create_session`, `require_session`, `touch_session`, `end_session`, and test helpers.
- [x] Store `workdir`, target, optional machine, optional worker session id, timestamps, and optional label.
- [x] Remove normal-path fallback to `DEFAULT_TOOL_SESSION_ID`.
- [x] Add unit tests for id format, uniqueness retry, missing session errors, workdir storage, and snapshot isolation.

### Slice 3: `session_start` tool

- [x] Add input/result models for `session_start`.
- [x] Add model-facing `session_start(target="local", workdir=".", machine=None, label=None)`.
- [x] Make `session_start` require an explicit `workdir` and add `session_change_cwd(session_id, workdir)` for correcting/changing session cwd.
- [x] Return `session_id`, target, workdir, and lightweight orientation/discovery metadata.
- [x] Remove `environment_info` from the default/model-facing surface.
- [x] Update MCP server instructions to start substantial workspace work with `session_start`.
- [x] Update docs and generated references.
- [x] Add tests proving `environment_info` is absent from the default MCP surface and `session_start` is present.

### Slice 4: Local session-bound read/search/edit

- [x] Make `read`, `search`, and `edit_lines` require `session_id`.
- [x] Resolve relative paths against the session workdir.
- [x] Ensure read/search snapshots are recorded under the explicit session.
- [x] Ensure `edit_lines` rejects missing session, unknown snapshot, cross-session snapshot, stale snapshot, and unseen ranges.
- [x] Update docs/generated references/tests.

### Slice 5: Local session-bound bash/job

- [x] Make `bash` require `session_id` and default cwd to the session workdir.
- [x] Bind tracked jobs to `session_id` in the job store.
- [x] Make `job` require `session_id` and list/poll/cancel/retry only jobs in that session.
- [x] Ensure job ids remain stable and job output does not expose shell internals unnecessarily.
- [x] Update tests for cross-session job isolation.

### Slice 6: Rename persistent shell handle to `shell_id`

- [x] Rename model-facing persistent shell parameters from `session_id` to `shell_id` for local shell companion tools.
- [x] Rename model-facing persistent remote shell parameters from `session_id` to `shell_id` for remote/worker internals that remain exposed.
- [x] Update result models to return `shell_id`; optionally include legacy `session_id` internally only where needed for compatibility tests.
- [x] Update descriptions, docs, generated references, and tests.
- [x] Add surface tests preventing persistent shell descriptions from calling shell handles agent `session_id`.

### Slice 7: Remote session start and dispatch

- [x] Extend `session_start` with `target="remote"`, required `machine`, and remote `workdir`.
- [x] On remote start, create a worker-side local session and store `worker_session_id` in the control-server session record.
- [x] Dispatch `read/search/edit_lines/bash/job` through the session record when `target="remote"`.
- [x] Propagate the worker session id to worker-side tools.
- [x] Add tests for remote session creation, remote read/search/edit/bash/job dispatch, and missing/offline worker errors.

### Slice 8: Delete generic `remote(...)`

- [x] Remove the generic `remote(machine, op, args)` model-facing tool.
- [x] Remove `remote` from generated references and server instructions.
- [x] Keep or adjust `remote_admin(...)` for control-plane invite/list/revoke/rename.
- [x] Ensure no model-facing docs recommend `remote(...)`.
- [x] Add surface tests proving `remote` is absent and remote work uses `session_start(target="remote")` plus normal tools.

### Slice 9: Remaining stateful tools and docs

- [x] Decide session policy for `write_file`, `delete_file_or_dir`, todos, file links, secret scan, and connector-style search/fetch.
- [x] Make workspace-affecting tools session-bound where appropriate.
- [x] Update user docs, examples, troubleshooting, generated references, and PR body.
- [x] Run full validation and update this document with final status.

## Current TODO

Latest completed session/tool-surface status:

- Slices 1-9 are complete and pushed on PR #79.
- Latest confirmed code/docs cleanup head before this final source-of-truth update is `bb78677 docs: sync session tool references`; PR checks were green and `mergeStateStatus` was `CLEAN`.
- The model-facing surface uses explicit agent/workspace sessions: `session_start(workdir=...)`, `session_change_cwd(session_id, workdir)`, and session-bound normal tools.
- `environment_info` and generic `remote(machine, op, args)` are absent from the model-facing MCP/HTTP/generated surface.
- Persistent shell handles are model-facing `shell_id`; agent/workspace sessions remain `session_id`.
- Slice 9 completed the remaining session policy: `list_files`, `write_file`, `delete_file_or_dir`, `secret_scan`, file-link tools, and todo tools require `session_id`; `workspace_search` and `fetch` remain sessionless read-only connector-compatible exceptions.
- Download links are owned by local agent sessions, todos are persisted per agent session, and HTTP GET tool routes pass query parameters while ignoring query `tool_name` overrides.
- Cleanup completed after review: removed unused `explanation` audit metadata, fixed typed coercion for HTTP GET query arguments, removed unexposed legacy remote facade code/tests/schemas, and refreshed docs/generated references.
- PR description has been rewritten with a detailed summary, scoped change list, validation checklist, and reviewer notes.

Current cleanup/hardening task:

Review follow-up hardening has been completed in small pushed commits, each with this source-of-truth document updated before commit and PR CI checked after push.

Current review iteration requested by the user has been implemented locally:

1. Shell execution implementation naming was merged: the public `bash` tool remains, but its operation, registry, input annotations, and result model now live in shell-named modules. The former parallel bash modules were deleted.
2. Model-facing descriptions/docstrings were expanded for shell tools, read/search/path-discovery tools, connector search/fetch, and todo tools.
3. Overlapping tools now include concise choice guidance in their model-facing descriptions.
4. `RemoteToolRegistry.register_mcp` now uses the declarative superclass registration path when remote tools are enabled, so `remote_admin` receives its normal metadata and description from ToolDefinition.
5. The public diff-application tool was removed entirely; command-driven diff application can be done through bash when needed, while normal precise edits should prefer grounded edit_lines.

1. P1 `run_python_code`: make it an explicit session-bound Python convenience wrapper over the bash execution surface. It now requires `session_id`, writes code to a temporary script, runs `python3 <temporary-script>`, defaults relative `cwd` to the session workdir, supports `timeout_s`, `max_output_bytes`, `env`, `async_`, `pty`, and `name`, and dispatches through remote sessions using the paired worker session. Local focused validation passed: ruff on touched files, `test_run_python_code_creates_temp_file`, and `test_mcp_metadata_for_chatgpt_developer_mode`.
2. P2 `tree_view` and `glob_search`: require `session_id`, resolve relative paths against the session workdir, dispatch through remote sessions, and update model-facing descriptions/MCP instructions. Local focused validation passed: ruff on touched files, `tests/test_search_ops.py`, `test_search_tool_input_and_output_schema_descriptions_are_exposed`, `test_mcp_metadata_for_chatgpt_developer_mode`, generated references refreshed, and live MCP schema confirmed `tree_view`/`glob_search` require `session_id`.
3. P3 surface guard: replace the partial stateful-tool test with a deny-by-default check so every model-facing tool must require `session_id` unless it is in the explicit sessionless allowlist (`session_start`, `version`, connector-compatible `workspace_search`/`fetch`, persistent-shell companion tools, and `remote_admin`). Local focused validation passed: `test_model_facing_tools_require_session_id_by_default` and `test_mcp_local_and_remote_tool_surface_is_stable`.
4. P4 stale public/config text: remove obsolete `read_many_files tool` references from settings descriptions and generated public config docs/examples, replacing them with internal multi-file read operation wording. Local focused validation passed: regenerated config examples/docs, confirmed no `read_many_files tool` matches remain in `.env.example`, `config.example.yaml`, generated configuration docs, or settings docstrings, ran ruff on settings, and `git diff --check`.
5. Final review cleanup: after P1-P4, deeper validation found remaining model-facing path descriptions that incorrectly said session-bound relative paths resolve inside the configured workspace. These descriptions now say relative paths resolve inside the agent/workspace session workdir, generated tool references were refreshed, and validation passed: ruff on touched files, focused ChatGPT metadata/schema tests, generated tools/instructions cmp checks, config generation check, `git diff --check`, full `ruff check src tests`, and full `pyright`.
Cross-context continuation prompt is maintained at the end of this file. It should be copied into a new AI context when handing off the task.

## Cross-context continuation prompt

```text
继续 local-shell-mcp 的 stateful session tool surface 重构。项目根目录是 `/workspace/local-shell-mcp-tool-compare`，分支是 `feat/agent-tool-surface`，PR 是 https://github.com/rijuyuezhu/local-shell-mcp/pull/79 。不要碰 `/workspace/local-shell-mcp`，那里有用户自己的未提交改动。

唯一信源是：`/workspace/local-shell-mcp-tool-compare/docs/maintenance/session-surface-redesign-plan.md`

请先读取这个文件，再检查 `git status`、最新 commits、PR diff 和 CI 状态，然后继续实现里面的当前 TODO。当前最新状态：Slice 1-9 已实现；review follow-up hardening commits through `50dca61 p4-config-text` 已完成并通过 PR CI。P1 `run_python_code` 已改为 required `session_id` 的 bash-like Python wrapper，支持 cwd/timeout/max_output/env/async_/pty/name 并通过 remote session dispatch。P2 `tree_view` 和 `glob_search` 已改为 required `session_id`，相对路径按 session workdir 解析，并通过 remote session dispatch。P3 surface guard 已改为 deny-by-default：除 `session_start`、`version`、connector-compatible `workspace_search`/`fetch`、persistent-shell companion tools、`remote_admin` 外，model-facing tools 必须 required `session_id`。P4 stale public/config `read_many_files tool` 文案已清理。Final cleanup 还修正了 session-bound 参数描述中 “configured workspace” 的残留，改为 session workdir 语义，并刷新 generated refs。

下一步：提交并推送 final cleanup commit，确认该 head 的 PR CI，通过后做最终 review/handoff。model-facing desc / generated refs / MCP instructions 只能描述当前可用能力，不要写 future slice / planned / once enabled 这类路线图措辞；路线图只放在这个计划文件里。
```




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

- `environment_info` compatibility is intentionally not kept; the public MCP/HTTP/generated surface now uses `session_start`. Generic `remote(...)` is removed from the model-facing surface; normal remote code work uses first-class remote sessions.
- Renaming persistent shell handles from `session_id` to `shell_id` may require compatibility shims or coordinated test updates.
- Remote paired session lifecycle needs careful cleanup if the control server session ends while the worker remains online, or if the worker restarts.
- Session persistence across server restarts is undecided. Initial implementation may be process-local, but the design should not preclude persisted sessions later.
- Project instruction discovery should be lightweight initially to avoid making `session_start` slow or noisy.
