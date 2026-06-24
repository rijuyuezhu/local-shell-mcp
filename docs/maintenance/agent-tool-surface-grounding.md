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

- The branch is functionally green through the model-facing hashline adoption pass.
- `hashline_edit` is available and generated into `docs/reference/generated/tools.json`.
- MCP/server instructions, model-facing tool descriptions, generated reference data, and guides now teach `hashline_edit` as the default edit path when the model is editing directly from copied `[path#snapshot_id]` plus `line:text` output.
- Existing `edit_lines` remains useful for structured/programmatic edits when the caller already has exact path/start/end/replacement arguments.
- Remote worker e2e coverage now exercises the first-class remote session path for `hashline_edit`: `tests/test_e2e_remote_worker.py` reads a remote file, applies `hashline_edit` from copied hashline grounding, then still applies `edit_lines` to keep structured remote edit coverage.
- Latest local validation for the adoption pass and remote follow-up:
  - focused surface/export tests passed: 51 passed, 1 warning.
  - `uv run pyright .` passed: 0 errors, 0 warnings, 0 informations.
  - generated tool/instruction reference check passed.
  - `uv run pytest -q` passed: 268 passed, 1 warning.
  - remote worker e2e focused test passed: `uv run pytest -q tests/test_e2e_remote_worker.py` -> 1 passed.

## Current read/edit/search comparison with oh-my-pi

Comparison baseline:

- `local-shell-mcp`: `/workspace/local-shell-mcp`, branch `feat/oh-my-pi-style-grounding`, including the model-facing hashline adoption pass and the remote e2e follow-up in this file.
- `oh-my-pi`: `/workspace/oh-my-pi`, fast-forwarded to current `origin/main` at `93d730c01` before comparison.

### Read surface

`local-shell-mcp` now has the important agent-facing grounding shape:

- `read(session_id, path)` is explicit-session and filesystem/workspace oriented.
- File output uses hashline-style grounding: `[path#snapshot_id]` plus `line:text` rows, with metadata including `session_id`, `snapshot_id`, seen ranges, and truncation state.
- Supported selectors are deliberately small: `path:50`, `path:50-80`, `path:50+20`, `path:raw`, and `path:50-80:raw`.
- Directory listing is available through `read` and also through specialized tools such as `list_files`, `tree_view`, and `glob_search`.

`oh-my-pi` read is broader and more integrated:

- It uses implicit session/cwd instead of requiring `session_id` in every call.
- One `read(path)` surface covers local files, directories, internal URIs, web URLs, archives, SQLite, documents, notebooks, images, and conflict views.
- It supports richer selectors, including multiple ranges such as `:5-16,960-973`, raw/range combinations, conflict selectors, archive member selectors, SQLite table/query selectors, and URL pagination.
- It can return structural summaries for parseable code and tells the model which ranges to re-read.
- Its hashline header uses a short content tag, e.g. `[src/foo.ts#1A2B]`, and is backed by a per-session snapshot store.

Practical delta: `local-shell-mcp` has the core editable read grounding, but `oh-my-pi` still has a much richer reader/router. Do not copy the full router unless there is a concrete product need; targeted future candidates would be multi-range selectors, richer document/URL codecs, or conflict-specific views.

### Search surface

`local-shell-mcp` search:

- `search(session_id, pattern, paths?, regex=true, case_sensitive=true, max_results?)` is a direct workspace text/code search.
- Results carry hashline grounding usable by both `hashline_edit` and `edit_lines`.
- `paths` can scope files/directories/globs, and results include grouped context, snapshot metadata, and displayed ranges.

`oh-my-pi` search:

- `search(pattern, paths?, case?, gitignore?, skip?)` is a discoverable built-in backed by fast text search.
- The prompt strongly tells the model to use the built-in `search` rather than shelling out to grep/ripgrep.
- `paths` accepts files, directories, globs, internal URLs, and file line selectors such as `src/foo.ts:50-100,200-300`.
- It has pagination via `skip`, gitignore control, file/match caps, and hashline output where match lines are marked while surrounding context remains editable grounding.

Practical delta: `local-shell-mcp` has safer and simpler grounded search for MCP use. `oh-my-pi` has more search ergonomics around pagination, gitignore control, line-scoped paths, internal resources, and stronger prompt-level discouragement of shell grep. Future local-shell-mcp work should consider these only if current search results become too noisy or hard to page.

### Edit surface

`local-shell-mcp` edit surface is split intentionally:

- `hashline_edit(session_id, input)` is the model-facing default for edits copied from `[path#snapshot_id]` plus `line:text` output.
- Current `hashline_edit` supports a deliberately small single-hunk grammar: copied rows plus `+replacement` rows, `SWAP start[-end]:`, and `INSERT [BEFORE|AFTER] line:`.
- `edit_lines(session_id, path, start_line, end_line, replacement, snapshot_id?)` remains the structured low-level tool when exact path/range/replacement data already exists.
- `write_file` is reserved for new files or intentional whole-file replacement.

`oh-my-pi` edit is more powerful and more complex:

- The essential model-facing tool is a single `edit` tool, currently with hashline mode as the main flow while retaining older patch/replace/apply-patch modes internally.
- Hashline input requires `[PATH#TAG]` and supports multi-section/multi-hunk edits.
- It has explicit operations such as `SWAP`, `DEL`, `INS.PRE`, `INS.POST`, `INS.HEAD`, `INS.TAIL`, plus block-aware forms such as `SWAP.BLK`, `DEL.BLK`, and `INS.BLK.POST`.
- It includes stale-tag recovery, seen-line validation, no-op loop protection, streaming diff preview support, and LSP diagnostics integration.

Practical delta: `local-shell-mcp` now has the important “copy grounded output into edit tool” workflow, but it intentionally avoids oh-my-pi's larger hashline grammar and LSP/editor integrations. The next reasonable edit-feature candidate, if needed, is multi-hunk `hashline_edit`; block-aware edits should wait until there is a parser/tree-sitter story and a clear user need.

## Recommended next slice

No immediate implementation slice is required for this grounding plan after the adoption pass, remote `hashline_edit` e2e follow-up, and current oh-my-pi comparison.

Keep these invariants for future slices:

- Do not remove `edit_lines`; keep it as the structured low-level precise edit tool.
- Keep `hashline_edit` as the model-facing default for copied hashline text.
- Model-facing tool descriptions and generated instructions must describe only currently available capabilities.
- Do not mention oh-my-pi or other external reference projects in model-facing tool descriptions or generated instructions.

If continuing, pick from these follow-ups only when there is a clear product need:

- Review stale user/docs examples outside `docs/guides/*` now that the main adoption pass is done.
- Consider whether `hashline_edit` should support multi-hunk input. Only do this if there is a clear product need; current single-hunk behavior is smaller and safer.
- Consider search ergonomics from the comparison: pagination, gitignore control, line-scoped path selectors, or stronger model-facing guidance against shell grep.
- Consider read ergonomics from the comparison: multi-range selectors, richer document/URL/archive readers, or conflict-specific read views.
- Review whether `ReadOutput.content` and `ReadOutput.numbered_content` naming should be simplified in a breaking-change slice.

## New-context prompt

Use this prompt to continue in a fresh context:

```text
继续 local-shell-mcp 的 agent-facing read/search/edit tool-surface grounding 重构。请用中文和我沟通，保持客观、直接。

项目根目录是 `/workspace/local-shell-mcp`，分支是 `feat/oh-my-pi-style-grounding`，远端分支同名。唯一信源是：`/workspace/local-shell-mcp/docs/maintenance/agent-tool-surface-grounding.md`。请先读取这个文件，再检查 `git status`、最近 commits、PR/branch diff 和 CI 状态，然后从该文件的 “Recommended next slice” 继续。

当前状态：
- `read` / `search` 已输出 hashline-style grounding：`[path#snapshot_id]` plus `line:text` rows。
- `hashline_edit(session_id, input)` 已实现、测试、生成引用、写入 model-facing instructions/docs，并作为 copied hashline text 的默认编辑流程。
- `edit_lines` 必须保留，作为已有 path/start/end/replacement 参数时的结构化低层精确编辑工具。
- 远端 worker e2e 已覆盖 first-class remote session 下的 `hashline_edit`，同时保留 `edit_lines` 远端覆盖。
- 唯一信源中已经记录了当前 `local-shell-mcp` 与当前 `oh-my-pi` 的 read/edit/search 对比结论。

不要重新设计已经完成的实现。当前没有必须继续做的 implementation slice；只有在用户明确选择时，才从唯一信源的 follow-up 列表中挑一个小 slice 做。做任何新 slice 时，保持 model-facing 描述只描述当前可用能力，不要在工具描述或 generated instructions 里提 oh-my-pi、future/planned 能力或内部架构词。完成后跑相关 focused tests、必要的 generated reference check、pyright/pytest，commit、push、看 CI，并更新唯一信源。
```
