# Agent tool surface grounding plan

This file is the single source of truth for the current agent-facing read/search/edit tool-surface refactor. Continue future work from this document before inspecting code. Keep it current after each slice.

## Current branch and repository

- Repository: `/workspace/local-shell-mcp`
- Branch: `feat/oh-my-pi-style-grounding`
- Remote branch: `origin/feat/oh-my-pi-style-grounding`
- PR context: tool-surface cleanup focused on making file context and edits easier and safer for coding agents.
- Communication preference from the user: Chinese, objective, direct.

## Constraints

- Work in `/workspace/local-shell-mcp` for this branch unless the user explicitly redirects.
- Do not treat older chat summaries as authoritative once this file exists; update this file instead.
- Model-facing tool descriptions and generated instructions must describe only currently available capabilities. Do not mention future slices, planned behavior, internal architecture labels, or external reference projects in model-facing surfaces.
- Prefer small, reviewable slices. After each complete slice: run focused tests, run generated-reference checks when tool descriptions/schemas/instructions change, run broader validation as appropriate, commit, push, and check CI.
- If pre-commit rewrites files, re-run the relevant checks before committing.
- Use explicit local-shell-mcp sessions with a required workdir. `session_id`-bound tools should be used for file inspection/edits.

## Completed slices

### `0153bd4 feat: simplify read output`

- `read` model-facing output changed to hashline-style text:
  - Header: `[path#snapshot_id]`
  - Rows: `line:text`
- `ReadOutput.file` became metadata-only and no longer repeats `content`, `numbered_content`, or `lines` inside `file`.
- `search` grounded match output also moved to `line:text` form while retaining snapshot and visible-range metadata.
- Existing `edit_lines` snapshot, stale-file, and seen-range checks continued to work.
- Generated tool reference was updated.
- Initial CI failed only because old e2e assertions still expected the previous shape.

### `4a4740c test: update e2e grounded output expectations`

- Updated REST/MCP HTTP/stdio e2e assertions for hashline read/search output.
- Adjusted a sorting-sensitive `workspace_search` assertion.
- Validation before push:
  - `uv run python -m pytest tests/test_e2e_http_rest.py tests/test_e2e_mcp_http.py tests/test_e2e_stdio.py -q` passed.
  - `uv run pyright .` passed.
  - generated tools reference check passed.
  - `uv run pytest -q` passed.
- CI run `28070156818` passed all jobs.

### `f02d10b feat: add hashline edit tool`

- Added `hashline_edit(session_id, input)`.
- Supported input forms:
  - Copied rows followed by replacement rows:
    ```text
    [path#snapshot_id]
    2:old text
    +new text
    ```
  - Delete copied rows by omitting `+` replacement rows.
  - `SWAP start[-end]:` followed by `+replacement` rows.
  - `INSERT [BEFORE|AFTER] line:` followed by `+inserted` rows.
- Reused the existing `edit_lines` snapshot/stale-file/seen-range validation path.
- Added old-text validation for direct copied-row edits so a mismatched copied line is rejected before editing.
- Added handling for workspace-root-relative hashline headers from nested session workdirs.
- Added remote worker allowlist entry for `hashline_edit`.
- Updated REST routes, e2e core tool list, generated tool reference, unit tests, tool-surface tests, and e2e workflow coverage.
- Validation before push:
  - `uv run python -m pytest tests/test_files_ops.py -q` passed.
  - `uv run python -m pytest tests/test_tool_surface.py -q` passed.
  - REST/MCP HTTP/stdio e2e tests passed.
  - `uv run pyright .` passed.
  - generated tools reference check passed.
  - `uv run pytest -q` passed: 267 passed, 1 warning.
- CI runs after push:
  - Docs `28073674665`: success.
  - CI `28073674648`: success across pre-commit, pyright, vscode-extension, Ubuntu pytest, and macOS pytest.

## Current known state

- The branch is functionally green through `f02d10b`.
- `hashline_edit` is available and generated into `docs/reference/generated/tools.json`.
- The underlying tool instructions and docs have not yet been fully adapted to prefer `hashline_edit` where it is now the better model-facing edit path.
- Existing `edit_lines` remains useful for structured/programmatic edits when the caller already has exact path/start/end/replacement arguments.

## Recommended next slice

Do a model-facing adoption pass for the now-available `hashline_edit` capability.

Rationale: the implementation is green, but several current model-facing or user-facing texts still teach the old default edit flow. That can make agents keep using `edit_lines` even when the hashline text they just saw can be edited more directly.

Scope for the next slice:

1. Update MCP/server instructions source so the default workflow says:
   - Use `read` and `search` for context.
   - Treat `[path#snapshot_id]` plus `line:text` rows as the authoritative edit grounding.
   - Prefer `hashline_edit` when editing directly from copied hashline output.
   - Use `edit_lines` when the caller already has structured path/start/end/replacement data.
2. Update model-facing tool descriptions where needed:
   - `read` should mention hashline output and `hashline_edit` as the direct edit companion.
   - `search` should mention that results can ground `hashline_edit` and `edit_lines`.
   - `bash` / `run_python_code` descriptions should not imply `edit_lines` is the only precise edit tool.
   - `write_file` should prefer `hashline_edit` or `edit_lines` for precise edits instead of only `edit_lines`.
   - Remote-admin normal-work examples should include `hashline_edit` if listing edit tools.
3. Update hand-written docs that still describe the old workflow:
   - `docs/guides/common-workflows.md`
   - `docs/guides/example-prompts.md`
   - `docs/guides/audit-log.md` because it still has an old `1|...` output example and repeated old metadata shape.
4. Regenerate generated references after model-facing text changes:
   - `docs/reference/generated/tools.json`
   - `docs/reference/generated/server-instructions.json`
5. Add or adjust tests that lock the intended text at a high level, preferably in existing surface tests rather than brittle full-string assertions.
6. Validate:
   - focused docs/tool-surface tests touched by the slice.
   - `uv run pyright .`
   - generated reference check.
   - `uv run pytest -q` when feasible.
7. Commit, push, and check CI.

Do not remove `edit_lines` in this slice. Treat `hashline_edit` as the model-facing default for copied hashline text, and `edit_lines` as the structured low-level precise edit tool.

## Later follow-ups after the adoption pass

- Consider whether `hashline_edit` should support multi-hunk input. Only do this if there is a clear product need; current single-hunk behavior is smaller and safer.
- Consider remote-specific e2e coverage for `hashline_edit` if remote CI coverage is already available and not too expensive.
- Review whether `ReadOutput.content` and `ReadOutput.numbered_content` naming should be simplified in a breaking-change slice. Do not do this while the user-facing workflow docs are stale.
- Review stale user/docs examples outside `docs/guides/*` after the main adoption pass.

## New-context prompt

Use this prompt to continue in a fresh context:

```text
继续 local-shell-mcp 的 agent-facing read/search/edit tool-surface grounding 重构。请用中文和我沟通，保持客观、直接。

项目根目录是 `/workspace/local-shell-mcp`，分支是 `feat/oh-my-pi-style-grounding`，远端分支同名。唯一信源是：`/workspace/local-shell-mcp/docs/maintenance/agent-tool-surface-grounding.md`。请先读取这个文件，再检查 `git status`、最近 commits、PR/branch diff 和 CI 状态，然后从该文件的 “Recommended next slice” 继续。

当前已完成并推送：
- `0153bd4 feat: simplify read output`
- `4a4740c test: update e2e grounded output expectations`
- `f02d10b feat: add hashline edit tool`

截至记录时，Docs run `28073674665` 和 CI run `28073674648` 都已成功。`hashline_edit(session_id, input)` 已实现、测试、生成引用并推送。

下一步不要重新设计已经完成的实现；优先做 model-facing adoption pass：更新 server/MCP instructions 源、相关工具描述、手写 docs 示例，让当前可用的 hashline read/search output 与 `hashline_edit` 成为默认模型编辑流程，同时保留 `edit_lines` 作为结构化低层编辑工具。改完后重新生成 reference，跑 focused tests、pyright、generated check、pytest，commit、push、看 CI。
```
