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


### `docs: clarify hashline edit as default`

- Tightened model-facing edit guidance so `hashline_edit` is clearly the default model editing path for existing files.
- Clarified `hashline_edit` usage in tool descriptions and server instructions:
  - Copy `[path#snapshot_id]` plus displayed `line:text` rows from `read`/`search`.
  - Provide final new content only as `+text` rows.
  - A copied-row edit with no `+` rows deletes those rows.
  - `SWAP start[-end]:` and `INSERT [BEFORE|AFTER] line:` are the supported explicit directive forms.
  - Re-ground from returned fresh context or a new `read` after every successful edit or stale/surprising result.
- Reworded `edit_lines` descriptions so it remains available but is only recommended when exact structured path/start/end/replacement data is already available.
- Strengthened `search` guidance to prefer built-in search over shell grep/ripgrep when editable grounded results are needed.
- Regenerated tool and server-instruction reference JSON.
- Validation before commit:
  - `uv run python -m pytest tests/test_tool_surface.py -q` passed: 29 passed, 1 warning.
  - `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json --check` passed.
  - `uv run pyright .` passed: 0 errors, 0 warnings, 0 informations.
  - `uv run pytest -q` passed: 268 passed, 1 warning.
  - Follow-up validation after regenerating with `--wrapped`: `uv run python -m pytest tests/test_tool_surface.py tests/test_export_tools_json.py -q` passed: 31 passed, 1 warning; `uv run mkdocs build --strict` passed.


### `feat: add search skip pagination`

- Added `skip` to the model-facing `search(session_id, pattern, paths?, regex?, case_sensitive?, max_results?, skip=0)` tool.
- `skip` omits earlier matches before returning and grounding the current page, so callers can page through noisy or truncated searches with the same pattern and paths.
- `GrepSearchOutput` now includes `skipped` to report the number of earlier matches skipped before the returned page.
- Remote session search forwarding passes `skip` through to the worker session.
- Search tool descriptions and generated reference data now document `skip` pagination and keep hashline grounding guidance intact.
- Validation before commit:
  - `uv run python -m pytest tests/test_search_ops.py tests/test_mcp_chatgpt_compat.py -q` passed: 30 passed, 1 warning.
  - `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json --check` passed.
  - `uv run python -m pytest tests/test_search_ops.py tests/test_mcp_chatgpt_compat.py tests/test_remote_facade.py -q` passed: 39 passed, 1 warning.
  - `uv run pyright .` passed: 0 errors, 0 warnings, 0 informations.
  - `uv run pytest -q` passed: 269 passed, 1 warning.


### `feat: add line-scoped search paths`

- Added line-scoped concrete file selectors to `search` paths, e.g. `paths="src/app.py:50-80"`.
- The selector is stripped before invoking ripgrep, and returned matches are filtered to the selected inclusive line range before `skip` pagination and hashline grounding.
- Directory, glob, and unscoped file paths keep their previous behavior.
- Search input schema, model-facing description, generated reference data, and schema tests now document line-scoped path selectors.
- Validation before commit:
  - `uv run python -m pytest tests/test_search_ops.py tests/test_mcp_chatgpt_compat.py -q` passed: 31 passed, 1 warning.
  - `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json --check` passed.
  - `uv run pyright .` passed: 0 errors, 0 warnings, 0 informations.
  - `uv run pytest -q` passed: 271 passed, 1 warning.

## Current known state

- The branch is functionally green through multi-hunk `hashline_edit`, search skip pagination, line-scoped search paths, and search match/context display markers.
- `hashline_edit` is available and generated into `docs/reference/generated/tools.json`.
- MCP/server instructions, model-facing tool descriptions, generated reference data, and guides now teach `hashline_edit` as the default edit path for existing files when the model is editing from copied `[path#snapshot_id]` plus `line:text` output.
- Existing `edit_lines` remains available for structured/programmatic edits when the caller already has exact path/start/end/replacement arguments, but it is no longer presented as a peer default for ordinary model edits.
- `search` now supports `skip` pagination, concrete file line-scoped path selectors such as `src/app.py:50-80`, and displayed context rows marked by `displayed_lines.kind` as `match` or `context`; `matches` remains actual matches only.
- Search `numbered_content` still uses copyable `[path#snapshot_id]` plus `line:text` rows, and context rows are editable grounding recorded in `seen_ranges`.
- Remote worker e2e coverage now exercises the first-class remote session path for `hashline_edit`: `tests/test_e2e_remote_worker.py` reads a remote file, applies `hashline_edit` from copied hashline grounding, then still applies `edit_lines` to keep structured remote edit coverage.
- Latest local validation for Slice B:
  - `uv run python -m py_compile src/local_shell_mcp/ops/search.py src/local_shell_mcp/schemas/result_models/search.py` passed.
  - `uv run pytest tests/test_search_ops.py -q` passed: 14 passed.
  - `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json --check` passed.
  - `uv run pytest tests/test_tool_surface.py tests/test_export_tools_json.py tests/test_search_ops.py -q` passed: 45 passed, 1 warning.
  - `uv run pyright` passed: 0 errors, 0 warnings, 0 informations.
  - `uv run pytest` passed: 277 passed, 1 warning.

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
- Current `hashline_edit` supports multiple non-overlapping hunks in one call. Hunk forms remain deliberately small: copied rows plus `+replacement` rows, copied rows with no `+` rows to delete, `SWAP start[-end]:`, and `INSERT [BEFORE|AFTER] line:`.
- `edit_lines(session_id, path, start_line, end_line, replacement, snapshot_id?)` remains the structured low-level tool when exact path/range/replacement data already exists.
- `write_file` is reserved for new files or intentional whole-file replacement.

`oh-my-pi` edit is more powerful and more complex:

- The essential model-facing tool is a single `edit` tool, currently with hashline mode as the main flow while retaining older patch/replace/apply-patch modes internally.
- Hashline input requires `[PATH#TAG]` and supports multi-section/multi-hunk edits.
- It has explicit operations such as `SWAP`, `DEL`, `INS.PRE`, `INS.POST`, `INS.HEAD`, `INS.TAIL`, plus block-aware forms such as `SWAP.BLK`, `DEL.BLK`, and `INS.BLK.POST`.
- It includes stale-tag recovery, seen-line validation, no-op loop protection, streaming diff preview support, and LSP diagnostics integration.

Practical delta: `local-shell-mcp` now has the important “copy grounded output into edit tool” workflow, including non-overlapping multi-hunk edits, but it intentionally avoids oh-my-pi's larger hashline grammar and LSP/editor integrations. Block-aware edits should wait until there is a parser/tree-sitter story and a clear user need.

## Planned follow-up slices selected by the user

The user explicitly selected all five follow-up goals below. Future agents should implement them as separate, small, reviewable slices unless a later user instruction changes the order or scope. These are planning targets only; do not describe a slice in model-facing tool descriptions or generated instructions until that slice is actually implemented and tested.

Keep these invariants for every slice:

- Do not remove `edit_lines`; keep it as the structured low-level precise edit tool.
- Keep `hashline_edit` as the model-facing default for copied hashline text.
- Model-facing tool descriptions and generated instructions must describe only currently available capabilities.
- Do not mention oh-my-pi or other external reference projects in model-facing tool descriptions or generated instructions.
- Prefer one feature per commit. After each complete slice: run focused tests, generated-reference checks when schemas/descriptions/instructions change, broader validation as appropriate, commit, push, and check CI.

### Slice A — `hashline_edit` multi-hunk input

Goal: let one `hashline_edit(session_id, input)` call contain multiple non-overlapping hunks and, where practical, multiple file sections, while preserving existing stale-file, seen-range, snapshot, and old-text validation.

Scope:

- Extend the parser/executor so a single input may contain multiple operations under one or more `[path#snapshot_id]` headers.
- Preserve current single-hunk forms exactly: copied rows plus `+replacement` rows, delete by copied rows with no `+` rows, `SWAP start[-end]:`, and `INSERT [BEFORE|AFTER] line:`.
- Apply hunks against original line numbers, not shifted post-edit line numbers.
- Reject overlapping or duplicate touched ranges in the same file.
- Return useful per-file or combined diffs plus fresh context sufficient for the next grounded edit. Keep the response compact.

Out of scope for this slice:

- Block-aware edits such as `SWAP.BLK` / `DEL.BLK`.
- Renames, creates, deletes of whole files, or arbitrary patch/apply-patch modes.
- Removing or hiding `edit_lines`.

Tests to add/update:

- Unit tests for multiple replacements in one file, insert + replace in one file, deletion + replacement in one file, and overlapping-range rejection.
- Unit or integration tests for multi-file input if implemented.
- Remote/session forwarding coverage if the public tool contract changes.
- Tool-surface tests ensuring descriptions explain multi-hunk syntax only after implementation.

Status: implemented in this slice. Current behavior:

- A single `hashline_edit(session_id, input)` call may include multiple non-overlapping hunks under the same `[path#snapshot_id]` header, separated by blank lines.
- Inputs may also repeat `[path#snapshot_id]` headers for additional sections, including multiple files in one call.
- Existing single-hunk forms are preserved: copied rows plus `+replacement`, delete by copied rows with no `+` rows, `SWAP start[-end]:`, and `INSERT [BEFORE|AFTER] line:`.
- Hunks are validated against original snapshot line numbers, then applied from bottom to top per file so earlier hunks do not shift later original-line coordinates.
- The executor rejects stale snapshots, unseen ranges, old-text mismatches, wrong paths, out-of-range lines, and overlapping touched ranges in the same file.
- The result remains compatible with the old `EditLinesOutput` fields and adds `hunk_count` plus per-hunk `hunks` with fresh post-edit contexts.

Validation run for this slice:

- `uv run python -m py_compile src/local_shell_mcp/ops/files.py src/local_shell_mcp/schemas/result_models/files.py src/local_shell_mcp/tools/registry/files.py`
- `uv run pytest tests/test_files_ops.py -q` → 30 passed
- `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json`
- `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json --check`
- `uv run pyright` → 0 errors
- `uv run pytest` → 275 passed, 1 warning

### Slice B — search match/context output markers

Goal: make `search` output more useful for editing by including nearby context lines and explicitly marking which rows are actual matches versus context, while keeping hashline grounding valid for rows that can be copied into `hashline_edit`.

Scope:

- Add match/context distinction to model-facing `search` output, for example match rows marked differently from surrounding context rows.
- Include a small, bounded amount of context around matches when useful, without making noisy searches too large.
- Preserve `GrepMatch` structured fields and existing hashline grounding (`snapshot_id`, `seen_range`, `numbered_line`) for editable displayed rows.
- Ensure `skip` pagination and line-scoped `paths` continue to work with context output.

Design cautions:

- Decide whether context rows are editable grounding or purely display context. If editable, they must be recorded in `seen_ranges`; if not, the output must clearly avoid suggesting they can be edited.
- Do not break consumers that expect `matches` to represent actual matches only.

Tests to add/update:

- Search result with context before/after a match.
- Multiple matches in one file with merged context windows.
- Pagination behavior with context enabled.
- Hashline edit from a displayed search row after context output changes.
- Generated reference/tool-surface tests for any new input parameters or output fields.

Status: implemented in this slice. Current behavior:

- `matches` remains actual matched lines only, preserving existing consumers.
- Search output now includes `displayed_lines`, with each displayed editable row marked as `kind="match"` or `kind="context"`.
- `displayed_lines` rows include line text, copyable `numbered_line`, snapshot metadata, file digest, and `seen_range` metadata.
- Search displays a bounded one-line context radius around returned matches and merges overlapping same-file context windows.
- Context display respects line-scoped `paths`; context does not leak outside the selected ranges.
- `numbered_content` keeps copyable `[path#snapshot_id]` plus `line:text` rows so displayed match/context rows can be copied into `hashline_edit`.

Validation run for this slice:

- `uv run python -m py_compile src/local_shell_mcp/ops/search.py src/local_shell_mcp/schemas/result_models/search.py`
- `uv run pytest tests/test_search_ops.py -q` → 14 passed
- `uv run ruff format src/local_shell_mcp/ops/search.py src/local_shell_mcp/schemas/result_models/search.py src/local_shell_mcp/tools/registry/search.py tests/test_search_ops.py`
- `uv run ruff check src/local_shell_mcp/ops/search.py src/local_shell_mcp/schemas/result_models/search.py src/local_shell_mcp/tools/registry/search.py tests/test_search_ops.py` → All checks passed
- `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json`
- `uv run python scripts/export-tools-json.py --wrapped --output docs/reference/generated/tools.json --instructions-output docs/reference/generated/server-instructions.json --check`
- `uv run pytest tests/test_tool_surface.py tests/test_export_tools_json.py tests/test_search_ops.py -q` → 45 passed, 1 warning
- `uv run pyright` → 0 errors, 0 warnings, 0 informations
- `uv run pytest` → 277 passed, 1 warning

### Slice C — explicit `search` gitignore control

Goal: add a model-facing `gitignore` control to `search` so callers can choose whether ignored files are searched, while documenting the default clearly.

Scope:

- Add `gitignore` input to `search`, using a simple boolean or nullable boolean with an explicit default.
- Preserve current default behavior unless there is a deliberate, tested reason to change it.
- Wire the option through local search and remote session forwarding.
- Update tool descriptions, input schema docs, generated reference JSON, and tests.

Design cautions:

- State the behavior in terms of current available capability only. Do not reference external tools or future search plans.
- Keep interaction with `paths`, globs, `skip`, and line-scoped selectors predictable.

Tests to add/update:

- Search excludes ignored files by default if that is current behavior, or includes them by default if current behavior does that; document whichever is true.
- Search with `gitignore=false` can include an ignored file.
- Search with `gitignore=true` respects ignore rules.
- Remote search forwards the option.
- MCP/tool schema tests cover the new input description.

### Slice D — `read` multi-range selectors

Goal: support `read(session_id, path="file.py:5-16,960-973")` so agents can request several precise windows from one file without multiple tool calls.

Scope:

- Extend read selector parsing to support comma-separated line ranges.
- Preserve existing selectors: `path:50`, `path:50-80`, `path:50+20`, `path:raw`, and `path:50-80:raw`.
- Output should remain hashline-style `[path#snapshot_id]` plus `line:text` rows, with clear separators or compact grouping between non-contiguous ranges.
- Record all displayed ranges in `seen_ranges` so later `hashline_edit` / `edit_lines` validation remains correct.
- Make truncation and metadata behavior clear for multi-range reads.

Out of scope for this slice:

- URL/document/archive readers.
- Conflict-specific read views.
- Structural code summaries.

Tests to add/update:

- Single file multi-range read with two non-contiguous ranges.
- Multi-range plus `:raw` behavior.
- Invalid range ordering and malformed selector rejection.
- `seen_ranges` contains exactly the displayed ranges.
- Editing a displayed line from a multi-range read succeeds; editing an undisplayed gap is rejected.
- Generated reference/tool-surface tests for selector descriptions.

### Slice E — stronger model-facing critical rules

Goal: strengthen model-facing tool descriptions and server instructions so agents reliably use `read`/`search`/`hashline_edit` correctly, without adding unsupported behavior.

Scope:

- Add concise, high-signal rules to current tool descriptions and MCP/server instructions.
- Emphasize that built-in `search` should be used for editable content search instead of shell grep/ripgrep when grounding matters.
- Emphasize `hashline_edit` body rows are final content only, edits must be tightly scoped, tags/snapshot ids must be copied not invented, and agents must re-ground after each edit.
- Clarify `write_file` is for new files or intentional whole-file replacement only.
- Keep descriptions shorter than the full external-reference prompt style; prefer compact rules that fit MCP tool descriptions.

Out of scope for this slice:

- Adding new edit/search/read capabilities.
- Mentioning external reference projects in generated or model-facing surfaces.
- Describing planned multi-hunk, gitignore, or multi-range capabilities before they are implemented.

Tests to add/update:

- Tool-surface tests asserting the key critical rules appear in descriptions/instructions.
- Generated reference check.
- `mkdocs build --strict` if docs are touched.

## New-context prompt

Use this prompt to continue in a fresh context:

```text
继续 local-shell-mcp 的 agent-facing read/search/edit tool-surface grounding 重构。请用中文和我沟通，保持客观、直接。

项目根目录是 `/workspace/local-shell-mcp`，分支是 `feat/oh-my-pi-style-grounding`，远端分支同名。唯一信源是：`/workspace/local-shell-mcp/docs/maintenance/agent-tool-surface-grounding.md`。请先读取这个文件，再检查 `git status --short --branch`、最近 commits、branch diff、是否有关联 PR、以及最新 GitHub Actions Docs/CI 状态，然后从该文件的 “Planned follow-up slices selected by the user” 继续。

当前已完成状态：
- `read` / `search` 已输出 hashline-style grounding：`[path#snapshot_id]` plus `line:text` rows。
- `search(session_id, pattern, paths?, ..., skip=0)` 已支持 `skip` 分页；`paths` 已支持 concrete file line selectors，如 `src/app.py:50-80,100+10`。
- `hashline_edit(session_id, input)` 已实现、测试、生成引用、写入 model-facing instructions/docs，并作为 copied hashline text 的默认编辑流程。
- `edit_lines` 必须保留，作为已有 path/start/end/replacement 参数时的结构化低层精确编辑工具。
- 远端 worker e2e 已覆盖 first-class remote session 下的 `hashline_edit`，同时保留 `edit_lines` 远端覆盖。
- 唯一信源中已经记录了当前 `local-shell-mcp` 与当前 `oh-my-pi` 的 read/edit/search 对比结论。

用户已明确选择要继续补五个目标，但不要一次性混在一个大改里。按小 slice 逐个实现：
1. `hashline_edit` multi-hunk input。
2. search match/context output markers。
3. explicit `search` gitignore control。
4. `read` multi-range selectors。
5. stronger model-facing critical rules。

不要重新设计已经完成的实现。做任何新 slice 时，保持 model-facing 描述只描述当前可用能力；不要在工具描述或 generated instructions 里提 oh-my-pi、future/planned 能力或内部架构词。每完成一个 slice，运行相关 focused tests、必要的 generated reference check、pyright/pytest 或 mkdocs，commit、push、看 CI，并更新唯一信源。
```
