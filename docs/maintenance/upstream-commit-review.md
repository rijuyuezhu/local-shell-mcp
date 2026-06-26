# Upstream Commit Implementation Review

This file tracks every upstream commit after the fork point used by Wenrui Huang's first fork-side commit. The review is functional: a commit is covered when the current fork provides the same user-visible behavior or maintenance outcome, even if the implementation lives in different modules or uses a different architecture.

Status values: **Implemented** means the fork covers the upstream behavior; **Implemented (adapted)** means the fork covers it through a different design; **Partial** means the main goal is covered with known differences; **Not adopted** means the fork intentionally does not carry that upstream direction or the commit only applies to obsolete upstream structure; **Recommended** means the upstream change should still be imported; **Split follow-up** means the idea is useful but needs a fork-specific design rather than a direct port.

| # | Date | Upstream commit | Subject | Fork status | Current fork handling |
|---:|---|---|---|---|---|
| 1 | 2026-06-12 | `37b87f1` | fix-html-output | **Implemented** | OAuth authorization-page fields are escaped in the split OAuth module. |
| 2 | 2026-06-12 | `de6d459` | fix-worker-vendor-path | **Implemented** | Remote worker bootstrap includes the vendored dependency path and is tested. |
| 3 | 2026-06-12 | `2afbde2` | check-release-version-match | **Implemented** | The release workflow validates that the release tag matches the project version. |
| 4 | 2026-06-12 | `ce2a9a7` | handle-truncated-unicode | **Implemented (adapted)** | Byte-limited text reads do not fail on partial UTF-8 characters. |
| 5 | 2026-06-12 | `390a18f` | fix-pattern-edge-case | **Implemented** | Search treats dash-prefixed queries as patterns, not options. |
| 6 | 2026-06-12 | `c971abd` | fix-git-add-path-separator | **Not adopted** | The old dedicated git-add wrapper is no longer part of the fork's tool surface. |
| 7 | 2026-06-12 | `0a7ee3f` | add-docker-build-ignore | **Implemented (adapted)** | The fork uses a stricter allowlist-style `.dockerignore`. |
| 8 | 2026-06-12 | `2593bc0` | fix-search-test-literal | **Implemented (test-adapted)** | Equivalent search tests are maintained against the split search module. |
| 9 | 2026-06-12 | `dc88eb3` | fix-oauth-import-order | **Not adopted** | This style-only change applied to an obsolete single-file OAuth module. |
| 10 | 2026-06-12 | `e761b07` | ci-search-test-guard | **Implemented** | Search tests skip when the configured `rg` binary is unavailable. |
| 11 | 2026-06-13 | `78fd6d5` | Raise public shell timeout cap to 120 seconds | **Partial** | The fork keeps a lower default cap but makes the cap configurable. |
| 12 | 2026-06-13 | `8e5a988` | Bump version to 2.3.0 | **Not adopted** | Upstream 2.x version bumps are superseded by the fork's 3.x version line. |
| 13 | 2026-06-13 | `e44a6ad` | Exclude cryptography from PyInstaller binaries | **Implemented** | The release binary build excludes the unused crypto dependency. |
| 14 | 2026-06-13 | `572d947` | Prepare v2.3.1 release | **Not adopted** | Upstream 2.x release metadata is not copied into the fork. |
| 15 | 2026-06-13 | `9b04a02` | Add public file link downloads | **Implemented (adapted)** | Download-link tools and routes exist under the fork's split modules. |
| 16 | 2026-06-13 | `0c3dc20` | Add remote file transfer tools | **Implemented (adapted)** | Remote file and directory transfer exists through the fork's transfer modules. |
| 17 | 2026-06-14 | `4384da8` | Add MCP output schemas | **Implemented (adapted)** | MCP output schemas are generated through the declarative registry and typed result models. |
| 18 | 2026-06-15 | `be33c71` | Add stable MCP tool surface coverage | **Implemented (adapted)** | Tool-surface tests cover the current declarative registry and HTTP/MCP exposure. |
| 19 | 2026-06-15 | `f92e662` | Normalize REST tool validation errors | **Implemented (adapted)** | REST validation and tool errors use structured HTTP error handling. |
| 20 | 2026-06-15 | `5f9682d` | Audit routed MCP tool calls | **Implemented (adapted)** | Routed tool calls are audited through MCP watchdogs and local invocation helpers. |
| 21 | 2026-06-15 | `5d01c5d` | Filter shell subprocess environment | **Implemented (policy-adapted)** | Shell subprocesses receive a filtered environment using the fork's fixed policy. |
| 22 | 2026-06-15 | `2516bd2` | Improve MCP tool descriptions | **Implemented (adapted)** | Tool descriptions are maintained in registry modules and generated into MCP schemas/docs. |
| 23 | 2026-06-15 | `2a308c8` | Add HTTP MCP parity coverage | **Implemented (adapted)** | HTTP and MCP tool exposure are derived from the same declarative registry. |
| 24 | 2026-06-15 | `60db561` | Add remote capability checks | **Implemented (adapted)** | Remote worker allowlists and capability checks are maintained in split remote modules. |
| 25 | 2026-06-15 | `e1ee6cf` | Add documentation site | **Implemented (adapted)** | The fork has a MkDocs site with its own information architecture. |
| 26 | 2026-06-15 | `19fe715` | Add MCP tool export script | **Implemented (adapted)** | Tool reference JSON is exported from the current MCP/declarative registry path. |
| 27 | 2026-06-15 | `acfbbfc` | Update metadata | **Not adopted** | Upstream package metadata and repository URLs are replaced by fork-owned metadata. |
| 28 | 2026-06-15 | `1c81534` | Fix lint in added tests | **Implemented (equivalent cleanup)** | Adapted tests are covered by pre-commit, pyright, and pytest. |
| 29 | 2026-06-15 | `7d71773` | Add agent bridge core modules | **Implemented (superseded)** | The fork has a fuller split agent bridge implementation. |
| 30 | 2026-06-15 | `2c9e262` | Add GitHub Pages docs deployment | **Implemented (adapted)** | The fork has a docs workflow that builds MkDocs and deploys Pages. |
| 31 | 2026-06-15 | `caa11f8` | Configure GitHub Pages workflow | **Implemented (adapted)** | The docs workflow is configured for the fork's Python and uv toolchain. |
| 32 | 2026-06-15 | `5f59004` | Polish documentation landing page | **Implemented (adapted)** | The fork maintains its own canonical docs landing page. |
| 33 | 2026-06-15 | `9a284ea` | Improve docs and multilingual coverage | **Partial** | General docs coverage exists, but upstream's localization set is not adopted. |
| 34 | 2026-06-15 | `65cfec4` | Use native docs internationalization | **Split follow-up** | Native docs i18n would need a fork-specific localization strategy and maintenance plan before it is enabled. |
| 35 | 2026-06-15 | `112e027` | Improve documentation structure and coverage | **Partial** | The fork has broad docs coverage but uses its own structure. |
| 36 | 2026-06-15 | `9ceac6b` | Expand documentation structure and tool reference | **Implemented (adapted)** | Generated tool/config reference files and the docs renderer cover this goal. |
| 37 | 2026-06-15 | `e49a142` | Add localized documentation pages | **Split follow-up** | Localized docs should be added only after the fork decides on i18n structure, source-of-truth docs, and translation maintenance. |
| 38 | 2026-06-15 | `ea79fa9` | Add native Windows persistent sessions | **Split follow-up** | A Windows-native persistent shell backend is useful, but it needs a separate design for process/session semantics and CI coverage. |
| 39 | 2026-06-15 | `4c838fe` | Add Windows ConPTY shell backend | **Split follow-up** | ConPTY support should be handled with the broader Windows persistent-session design rather than ported directly. |
| 40 | 2026-06-15 | `a3a6267` | Bump version to 2.6.0 | **Not adopted** | Upstream 2.x version bumps are superseded by the fork's 3.x version line. |
| 41 | 2026-06-15 | `b30781c` | Fix remote worker join bootstrap | **Implemented (adapted)** | Remote worker join/bootstrap exists through the split worker entrypoint, join script, bundle, and tests. |
| 42 | 2026-06-16 | `3382d10` | Fix remote worker dependency bootstrap | **Implemented (adapted)** | The worker bootstrap path avoids importing server-only dependencies until local tool execution is needed. |
| 43 | 2026-06-16 | `e91fbf0` | Fix remote worker HTTP client behind Cloudflare | **Implemented (adapted)** | Worker POSTs prefer curl, keep a urllib fallback, and handle non-2xx and invalid JSON responses. |
| 44 | 2026-06-17 | `2581856` | Keep remote workers retrying connection failures | **Implemented** | Worker registration, polling, and result submission retry transient connection failures. |
| 45 | 2026-06-17 | `4283bce` | remote reconnect | **Implemented (adapted)** | Remote worker identity persistence, control-side resume, and `/remote/resume` are implemented. |
| 46 | 2026-06-17 | `5f0de67` | Add purpose metadata to risky tool calls | **Implemented (adapted)** | Shell/Python execution tools keep optional purpose metadata in the schema and normal tool-call audit. |
| 47 | 2026-06-17 | `e778822` | Add tracked job management tools | **Implemented (adapted)** | Local and remote tracked job operations exist through the fork's job registry and result models. |
| 48 | 2026-06-17 | `fd8411f` | Report remote worker status counts | **Implemented** | Remote machine listing reports online/offline/total counts and queue/last-seen information. |
| 49 | 2026-06-17 | `10f7806` | Add built-in version reporting | **Implemented (adapted)** | CLI, HTTP, and MCP version reporting exist and report the fork's version line. |
| 50 | 2026-06-17 | `4e90402` | Expand CI smoke coverage | **Partial** | The fork has pre-commit, pyright, pytest on Linux/macOS, and VS Code extension build checks, but not the exact upstream smoke matrix. |
| 51 | 2026-06-17 | `5511920` | Fix lint for new tool modules | **Implemented (equivalent cleanup)** | The fork's current modules are maintained under its lint/type/test pipeline. |
| 52 | 2026-06-17 | `45abb91` | Bump version to 2.7.0 | **Not adopted** | Upstream 2.x version bumps are superseded by the fork's 3.x version line. |
| 53 | 2026-06-17 | `58049c7` | Fix localized docs translations | **Split follow-up** | Translation fixes become relevant only if the fork adopts localized docs as a separate i18n effort. |
| 54 | 2026-06-17 | `a0a60db` | Add docs i18n regression check | **Split follow-up** | An i18n regression check should be added only with a fork-specific docs localization setup. |
| 55 | 2026-06-17 | `8262a39` | Handle remote worker KeyboardInterrupt cleanly | **Implemented** | The worker CLI handles interrupt shutdown cleanly. |
| 56 | 2026-06-18 | `4514979` | Refine MCP tool security scopes | **Implemented (adapted)** | Tool security scopes are split by read/write/execute/download-style capabilities in generated MCP metadata. |
| 57 | 2026-06-23 | `91d0c9c` | ci-matrix-update | **Partial** | Added fork-specific package, Compose, release-matrix, Dockerfile, and VS Code packaging smoke coverage; release Docker publishing now covers amd64/arm64, while the large upstream endpoint test matrix is intentionally not adopted. |
| 58 | 2026-06-23 | `713197d` | fix-ci | **Not adopted** | This only relaxes upstream's obsolete MCP metadata/scope tests; the fork should keep tests aligned to its current registry and scopes. |
| 59 | 2026-06-23 | `b5f7825` | fix-ci-2 | **Not adopted** | This continues relaxing obsolete upstream tests and does not change fork behavior. |
| 60 | 2026-06-23 | `af6061d` | fix-ci-3 | **Partial** | Cross-platform VSIX packaging reliability is covered by a Node packaging script; macOS Homebrew/runtime-tool install changes remain unnecessary for the current CI shape. |
| 61 | 2026-06-24 | `954e1ed` | fix-ci-4 | **Split follow-up** | Cross-platform test helpers are useful only if the fork adds Windows pytest coverage. |
| 62 | 2026-06-24 | `0543330` | fix-ci-5 | **Implemented (adapted)** | VSIX packaging now uses a cross-platform Node script and CI runs the VS Code extension job on Ubuntu and Windows. |
| 63 | 2026-06-26 | `aba28d8` | ci: reduce warning annotations | **Implemented (adapted)** | Dockerfile CI now uses lightweight amd64/arm64 BuildKit checks instead of full PR image builds; the Dockerfile was reduced to an Ubuntu 26.04 uv-managed runtime, and release-only Docker publishing remains responsible for real image builds. |
| 64 | 2026-06-26 | `5c7121d` | ci: avoid Homebrew tap trust warnings | **Split follow-up** | macOS Homebrew handling is only needed if the fork adds explicit macOS runtime-tool installation steps. |
| 65 | 2026-06-26 | `1b2b97d` | config: remove unused allow_network setting | **Implemented** | Removed the unused setting from runtime config, surface metadata, tests, examples, and generated configuration reference. |
| 66 | 2026-06-26 | `f444f56` | remote: enforce worker text input limits | **Implemented (adapted)** | Worker calls route through current local handlers, and large text inputs are already checked by shared text-size helpers; add regression tests if touched. |
| 67 | 2026-06-26 | `5ae46b4` | shell: send tmux input literally | **Implemented** | Persistent-shell input now sends text with literal `tmux send-keys -l` and sends Enter as a separate key event. |
| 68 | 2026-06-26 | `a63abeb` | search: return leading grep matches | **Implemented (adapted)** | Search now reads direct `rg --json` subprocess output incrementally and stops after the leading requested matches, avoiding shell tail truncation. |
| 69 | 2026-06-26 | `82b1b3b` | scan: honor gitignore in secret scan | **Implemented (adapted)** | `secret_scan` now prefers `rg --files` so ignore rules are honored, with a pathspec fallback for environments without ripgrep. |
| 70 | 2026-06-26 | `fa62aa1` | transfer: reject directory symlinks during pack | **Implemented** | Directory transfer packing now rejects symlink roots and symlink members before archive creation. |
| 71 | 2026-06-26 | `4467760` | vscode: stop Windows process trees | **Implemented** | The VS Code extension now stops Windows server process trees with `taskkill /T /F`, falling back to normal process kill on error and non-Windows platforms. |
| 72 | 2026-06-26 | `d0cb047` | tools: mark read-only tools | **Implemented (adapted)** | Declarative read-only annotations were added to the fork's current read/list/search/status-style tools and generated tool reference. |
| 73 | 2026-06-26 | `55a2e59` | scan: reduce placeholder secret noise | **Implemented (adapted)** | Generic assignment findings now skip obvious placeholder, fixture, and repeated-character values while preserving stronger token/private-key patterns. |
| 74 | 2026-06-26 | `2e6ef5a` | chore: prepare 2.7.3 | **Not adopted** | Upstream 2.x version bumps are superseded by the fork's 3.x version line. |
| 75 | 2026-06-26 | `f4dfdae` | search: avoid shell-specific grep pipeline | **Implemented (adapted)** | Search uses direct `rg` subprocess execution and keeps fork-specific grounding metadata, selectors, pagination, and structured missing-ripgrep errors. |
| 76 | 2026-06-26 | `95bce13` | chore: bump version to 2.7.4 | **Not adopted** | Upstream 2.x version bumps are superseded by the fork's 3.x version line. |
| 77 | 2026-06-26 | `e1f2dc0` | fix frozen shell loader environment | **Implemented (adapted)** | Shell subprocess environment filtering now restores original loader variables for frozen app bundles and removes bundled loader values when no original exists. |
