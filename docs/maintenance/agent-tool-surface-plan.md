# Agent-oriented tool surface redesign

This branch redesigns `local-shell-mcp`'s tool surface around focused coding-agent workflows. Treat this document and the draft PR description as the cross-session source of truth for ongoing work on this branch.

## Current status

Branch: `feat/agent-tool-surface`

The first implementation slice is focused on read grounding:

- add lightweight process-local tool session state;
- make file reads return original line numbers, model-facing `numbered_content`, file hashes, snapshot ids, and visible line ranges;
- update MCP server instructions and docs to teach agents to use numbered reads before editing.

## Design direction

`local-shell-mcp` should keep its Python/Pydantic/FastMCP structure, but expose a smaller and more semantic default tool surface for agents:

- `read`: read with selectors, line numbers, snapshots, and visible ranges.
- `search`: content search whose snippets can ground later edits.
- `edit_lines` / later `edit`: line-range editing with snapshot and visible-range checks.
- `bash`: one entry point for bounded commands, tracked jobs, and PTY/persistent shells.
- `remote`: one entry point for normal remote workspace operations, including session and transfer sub-ops; `remote_admin` handles invite/list/revoke/rename control-plane actions.

Existing low-level tools can remain during migration, but MCP instructions should guide agents toward the semantic tools.

## TODO

### Slice 1: read grounding

- [x] Add lightweight tool session store with a default session workaround for MCP clients that do not expose stable sessions.
- [x] Add `LineRange` and `ReadLine` result models.
- [x] Extend `ReadFileOutput` with line numbers, `numbered_content`, `session_id`, `snapshot_id`, `file_sha256`, and `seen_ranges`.
- [x] Update file-read operations to record displayed ranges in the session store.
- [x] Update MCP server instructions and docs for numbered reads.
- [x] Run targeted tests for the read-grounding slice.
- [ ] Publish branch and open draft review.

### Slice 2: path selectors and unified `read`

- [x] Add a parser for `path:selector` forms such as `src/foo.py:50-100`, `src/foo.py:50+20`, and `src/foo.py:raw`.
- [x] Add `read(path, session_id=None)` for selected file and directory reads.
- [x] Support directory listing through `read`.
- [x] Remove split file-read tools from the default public tool surface; keep their ops as internal implementation details for `read`, `search`, and tests.

### Slice 3: grounded line editing

- [x] Add `edit_lines(path, start_line, end_line, replacement, snapshot_id=None, session_id=None)`.
- [x] Reject stale snapshots when file hashes changed.
- [x] Reject edits outside visible ranges when session grounding is available.
- [x] Return unified diff and post-edit numbered context.
- [x] Mint a fresh snapshot after successful edits.

### Slice 4: search grounding

- [x] Extend `grep_search` output with line-numbered snippets and visible ranges.
- [x] Add `search(pattern, paths=None, ...)` for grounded content search.
- [x] Record displayed search snippets in the tool session store.

### Slice 5: remote organization

- [x] Add `remote(machine, op, args, session_id=None)` for selected remote operations.
- [x] Route normal remote workspace operations through `remote(op=...)`.
- [x] Keep remote invite/list/revoke/rename and transfer tools as explicit control-plane operations. Superseded by Slice 9, which collapses these into `remote_admin` and `remote(op="transfer")` for the MCP-facing surface.
- [x] Update MCP instructions so agents prefer `remote(op=...)` over choosing among many `remote_*` duplicates.

### Slice 6: bash tool

- [x] Add `bash(command, cwd='.', timeout_s=None, env=None, async_=False, pty=False, name=None)`.
- [x] Route bounded commands to `run_shell_command`.
- [x] Route async jobs to the tracked-job implementation.
- [x] Route PTY/interactive cases to persistent shell tools.

### Slice 7: descriptions, docs, and generated references

- [x] Rewrite tool descriptions around agent workflows, grounding, stale checks, and remote usage.
- [ ] Regenerate tool and server-instruction reference JSON.
- [x] Update tests that assert schema descriptions.
- [x] Update user-facing docs and examples.

### Slice 8: remove compatibility-layer surface

Goal: once the focused semantic tools are documented and generated references are current, keep the default agent-facing tool set small instead of exposing both compact tools and every legacy duplicate.

- [x] Decide which low-level compatibility tools should remain HTTP/local-invocation internals versus MCP-visible tools.
  - [x] Rename vague `agent_surface` modules/registry to clearer `read` tool naming.
- [x] Hide or remove legacy default-surface tools now covered by `read`, `search`, `edit_lines`, `bash`, and `remote`.
  - [x] Collapse split local job tools and explicit remote job tools into one `job` companion used with `bash(async_=true)` and `remote(op="job")`.
  - [x] Remove public wrappers covered by `read`, `search`, `bash`, and `remote`; keep reusable ops/models only where compact tools still depend on them.
- [x] Keep explicit control-plane and escape-hatch tools only where they are still necessary.
- [x] Update tool-surface tests, docs, generated references, and PR description.

### Slice 9: consolidate remaining remote surface

Goal: reduce remote-specific MCP tools further so models use `remote(machine, op, args)` by default instead of hallucinating among many `remote_*` variants.

- [x] Move remaining remote persistent-session companion actions behind `remote(op="session")`.
- [x] Consolidate remote transfer helpers behind `remote(op="transfer")` instead of exposing many `remote_copy_*` / `remote_pull_*` / `remote_push_*` MCP tools.
- [x] Collapse remote control-plane affordances into `remote_admin(action, args)` for invite/list/revoke/rename.
- [x] Update tests, docs, generated references, PR description, and CI.

## Validation checklist per slice

Run the smallest useful checks after each slice, then commit and push:

```bash
uv run pytest tests/test_files_ops.py tests/test_mcp_chatgpt_compat.py
uv run pyright
pre-commit run --all-files
```

For PR/CI:

```bash
git push -u origin feat/agent-tool-surface
gh pr create --draft --base main --head feat/agent-tool-surface
gh pr checks --watch
```
