# Agent-oriented tool surface redesign

This branch redesigns `local-shell-mcp`'s tool surface around coding-agent workflows inspired by oh-my-pi. Treat this document and the draft PR description as the cross-session source of truth for ongoing work on this branch.

## Current status

Branch: `feat/agent-tool-surface`

The first implementation slice is focused on read grounding:

- add lightweight process-local tool session state;
- make `read_file` return original line numbers, model-facing `numbered_content`, file hashes, snapshot ids, and visible line ranges;
- update MCP server instructions and docs to teach agents to use numbered reads before editing.

## Reference points from oh-my-pi

Local reference checkout: `/workspace/oh-my-pi`

Important files:

- `packages/coding-agent/src/tools/read.ts`
  - `read(path)` unifies files, directories, URLs, archives, and line selectors;
  - output separates model-facing content from structured details;
  - read/search record displayed lines for later editing.
- `packages/coding-agent/src/tools/search.ts`
  - search results include line-numbered snippets and snapshot tags;
  - search results can be used as edit grounding.
- `packages/hashline/src/prompt.md`
  - edits must reference a fresh `[PATH#TAG]` and original line numbers;
  - stale anchors are rejected and the agent must re-read.
- `packages/coding-agent/src/edit/index.ts`
  - one `edit` tool supports multiple editing modes while keeping grounding rules centralized.

## Design direction

`local-shell-mcp` should keep its Python/Pydantic/FastMCP structure, but expose a smaller and more semantic default tool surface for agents:

- `read` / improved `read_file`: read with selectors, line numbers, snapshots, and visible ranges.
- `search`: content search whose snippets can ground later edits.
- `edit_lines` / later `edit`: line-range editing with snapshot and visible-range checks.
- `bash`: one facade over bounded commands, tracked jobs, and PTY/persistent shells.
- `remote`: one facade over normal remote workspace operations, keeping invite/list/revoke/transfer as separate control-plane tools.

Existing low-level tools can remain during migration, but MCP instructions should guide agents toward the semantic tools.

## TODO

### Slice 1: read grounding

- [x] Add lightweight tool session store with a default session workaround for MCP clients that do not expose stable sessions.
- [x] Add `LineRange` and `ReadLine` result models.
- [x] Extend `ReadFileOutput` with line numbers, `numbered_content`, `session_id`, `snapshot_id`, `file_sha256`, and `seen_ranges`.
- [x] Update `read_file_execute` to record displayed ranges in the session store.
- [x] Update MCP server instructions and docs for numbered reads.
- [x] Run targeted tests for the read-grounding slice.
- [ ] Publish branch and open draft review.

### Slice 2: path selectors and unified `read`

- [x] Add a parser for `path:selector` forms such as `src/foo.py:50-100`, `src/foo.py:50+20`, and `src/foo.py:raw`.
- [x] Add a high-level `read(path, session_id=None)` facade.
- [x] Support directory listing through `read`.
- [x] Keep `read_file` as the lower-level compatibility path.

### Slice 3: grounded line editing

- [x] Add `edit_lines(path, start_line, end_line, replacement, snapshot_id=None, session_id=None)`.
- [x] Reject stale snapshots when file hashes changed.
- [x] Reject edits outside visible ranges when session grounding is available.
- [x] Return unified diff and post-edit numbered context.
- [x] Mint a fresh snapshot after successful edits.

### Slice 4: search grounding

- [x] Extend `grep_search` output with line-numbered snippets and visible ranges.
- [x] Add high-level `search(pattern, paths=None, ...)` facade.
- [x] Record displayed search snippets in the tool session store.

### Slice 5: remote organization

- [x] Add a high-level `remote(machine, op, args, session_id=None)` facade.
- [x] Route normal remote workspace operations through the facade.
- [x] Keep remote invite/list/revoke/rename and transfer tools as explicit control-plane operations.
- [x] Update MCP instructions so agents prefer `remote(op=...)` over choosing among many `remote_*` duplicates.

### Slice 6: bash facade

- [x] Add `bash(command, cwd='.', timeout_s=None, env=None, async_=False, pty=False, name=None)`.
- [x] Route bounded commands to `run_shell_command`.
- [x] Route async jobs to `job_start`.
- [x] Route PTY/interactive cases to persistent shell tools.

### Slice 7: descriptions, docs, and generated references

- [ ] Rewrite tool descriptions around agent workflows, grounding, stale checks, and remote facade usage.
- [ ] Regenerate tool and server-instruction reference JSON.
- [ ] Update tests that assert schema descriptions.
- [ ] Update user-facing docs and examples.

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
