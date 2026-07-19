# Upstream Commit Implementation Review

This file tracks every upstream commit after the fork point used by Wenrui Huang's first fork-side commit. The review is functional: a commit is covered when the current fork provides the same user-visible behavior or maintenance outcome, even if the implementation lives in different modules or uses a different architecture.

Status values: **Implemented** means the fork covers the upstream behavior; **Implemented (adapted)** means the fork covers it through a different design; **Partial** means the main goal is covered with known differences; **Not adopted** means the fork intentionally does not carry that upstream direction or the commit only applies to obsolete upstream structure; **Recommended** means the upstream change should still be imported; **Split follow-up** means the idea is useful but needs a fork-specific design rather than a direct port; **Pending** means the commit has been inventoried for the current migration branch but its fork-specific implementation decision is not complete yet.

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

<!-- upstream-port-placeholder: e1f2dc0..upstream/main -->

## Current upstream migration inventory

The rows below cover every commit currently reachable from `upstream/main` after the shared fork point `e1f2dc0`. They are intentionally initialized as placeholders on the feature-port branch and must be updated as each functional batch is reviewed, adapted, validated, or intentionally rejected.

| # | Date | Upstream commit | Subject | Fork status | Current fork handling |
|---:|---|---|---|---|---|
| 78 | 2026-07-07 | `ade54ef` | docs: improve Chinese translations | **Pending** | Pending functional review and fork-specific port decision. |
| 79 | 2026-07-07 | `0be3f73` | ci: publish Docker images to GHCR | **Pending** | Pending functional review and fork-specific port decision. |
| 80 | 2026-07-07 | `0232135` | ci: simplify release assets | **Pending** | Pending functional review and fork-specific port decision. |
| 81 | 2026-07-07 | `0aa9d66` | chore: update version metadata | **Pending** | Pending functional review and fork-specific port decision. |
| 82 | 2026-07-07 | `71b9605` | ci: simplify Docker release notes | **Pending** | Pending functional review and fork-specific port decision. |
| 83 | 2026-07-13 | `3820950` | skills: add fixed list and load tools | **Implemented (adapted)** | The fork already had fixed `list_agent_skills`/`activate_agent_skill` tools; this batch keeps those names and adds bounded `read_agent_skill_file` rather than adopting upstream tool names. |
| 84 | 2026-07-13 | `ddb1ea6` | skills: remove dynamic tool registration plumbing | **Not adopted** | The fork intentionally retains dynamic Skill and MCP bridge tools; session-local capabilities will use fixed session-aware tools instead of changing the global dynamic tool surface. |
| 85 | 2026-07-13 | `a63f32c` | docs: document fixed Skills workflow | **Implemented (adapted)** | Agent Bridge documentation now describes the fork-specific fixed Skill workflow and related-file reader while preserving dynamic tools. |
| 86 | 2026-07-13 | `fd210be` | chore: bump version to 2.9.0 | **Pending** | Pending functional review and fork-specific port decision. |
| 87 | 2026-07-13 | `386b0e8` | fix: derive state paths correctly on Windows | **Implemented (adapted)** | The fork derives `audit_log_path` and `agent_config_dir` from normalized `state_dir` properties instead of synchronizing independent defaults; custom-state regression coverage includes both dependent paths. |
| 88 | 2026-07-13 | `384f84b` | fix: derive agent paths from custom state directory | **Implemented (adapted)** | A custom `state_dir` already drives the fork's Agent Bridge config and audit paths through dynamic properties, with regression coverage. |
| 89 | 2026-07-13 | `0be1eff` | fix: expose readable Skill resource paths | **Implemented (adapted)** | Related files are exposed as canonical paths relative to the Skill directory, with VCS/cache metadata excluded. |
| 90 | 2026-07-13 | `971eb1e` | fix: validate Skill names and REST inputs | **Implemented (adapted)** | Skill names and related-file paths receive strict portable validation through the fork's existing declarative HTTP/MCP schemas. |
| 91 | 2026-07-13 | `2ee0188` | fix: bound and directly load Skill files | **Implemented (adapted)** | Skill discovery, activation, and related-file reads are bounded by registered fork settings and do not read every Skill body during listing. |
| 92 | 2026-07-13 | `1fa8d4a` | fix: parse Skill descriptions consistently | **Implemented** | YAML/TOML front matter and Markdown fallback descriptions are parsed consistently with bounded output. |
| 93 | 2026-07-13 | `d74bbee` | fix: harden Skill registry edge cases | **Implemented (adapted)** | The existing Agent Bridge scanner now has bounded traversal, regular-file checks, warning caps, VCS/cache exclusions, and path containment checks. |
| 94 | 2026-07-13 | `356a1af` | docs: document hardened Skill workflow | **Implemented (adapted)** | The hardened workflow is documented using the fork's existing Agent Bridge names and architecture. |
| 95 | 2026-07-13 | `3904578` | chore: bump version to 2.9.1 | **Pending** | Pending functional review and fork-specific port decision. |
| 96 | 2026-07-13 | `ac2b08d` | fix: close remaining Skill path and scan gaps | **Implemented (adapted)** | Remaining path, scan-budget, symlink, and file-size edge cases are covered in the fork scanner and tests. |
| 97 | 2026-07-13 | `de1897a` | test: limit invalid-byte filename case to Linux | **Pending** | Pending functional review and fork-specific port decision. |
| 98 | 2026-07-13 | `63d9064` | fix: normalize Skill text across platforms | **Implemented** | Skill text reads normalize CRLF and CR line endings while preserving the original byte count. |
| 99 | 2026-07-13 | `78c5b05` | feat(ui): add shared human interface backend | **Pending** | Pending functional review and fork-specific port decision. |
| 100 | 2026-07-13 | `70b2e7b` | feat(ui): add shared OpenTUI and web terminal client | **Pending** | Pending functional review and fork-specific port decision. |
| 101 | 2026-07-13 | `01315ea` | feat(ui): secure native and browser interface sessions | **Pending** | Pending functional review and fork-specific port decision. |
| 102 | 2026-07-13 | `c715917` | build(ui): package OpenTUI sidecars and Yazi | **Pending** | Pending functional review and fork-specific port decision. |
| 103 | 2026-07-13 | `aed3c3a` | docs(ui): document the human interface | **Pending** | Pending functional review and fork-specific port decision. |
| 104 | 2026-07-13 | `e3c429a` | test(ui): add OAuth browser end-to-end coverage | **Pending** | Pending functional review and fork-specific port decision. |
| 105 | 2026-07-13 | `b670769` | chore(release): prepare v3.0.0 | **Pending** | Pending functional review and fork-specific port decision. |
| 106 | 2026-07-13 | `fd66537` | fix(ui): harden the Windows ConPTY bridge | **Pending** | Pending functional review and fork-specific port decision. |
| 107 | 2026-07-13 | `2fb1ff4` | test(ui): validate PTY bridges on every platform | **Pending** | Pending functional review and fork-specific port decision. |
| 108 | 2026-07-13 | `8d3055d` | fix(build): scope Playwright Docker argument globally | **Pending** | Pending functional review and fork-specific port decision. |
| 109 | 2026-07-13 | `b368873` | docs(ui): translate the human-interface nav label | **Pending** | Pending functional review and fork-specific port decision. |
| 110 | 2026-07-13 | `4ac8693` | fix(ui): require OAuth on browser WebSockets | **Pending** | Pending functional review and fork-specific port decision. |
| 111 | 2026-07-13 | `8e40343` | fix(ui): make file management lossless and workspace-safe | **Pending** | Pending functional review and fork-specific port decision. |
| 112 | 2026-07-13 | `221715d` | fix(ui): make raw terminal input exclusive and ordered | **Pending** | Pending functional review and fork-specific port decision. |
| 113 | 2026-07-13 | `97258f8` | fix(ui): bound terminal requests and session cleanup | **Pending** | Pending functional review and fork-specific port decision. |
| 114 | 2026-07-13 | `080f68a` | fix(ui): preserve Windows TUI command paths | **Pending** | Pending functional review and fork-specific port decision. |
| 115 | 2026-07-13 | `a13b302` | fix(build): install Docker Python deps in a venv | **Pending** | Pending functional review and fork-specific port decision. |
| 116 | 2026-07-13 | `98369c6` | fix(auth): bound dynamic OAuth state and require S256 | **Implemented (adapted)** | The split OAuth service now requires explicit S256 PKCE, validates RFC 7636 challenge/verifier syntax, and bounds only unused, unexpired authorization codes through configurable capacity without evicting live state. Issue/exchange operations are serialized, capacity is checked before first-client approval persistence, and exhaustion is rendered in the local authorization form. Existing fork-native registration limits and approved-client persistence replace the upstream monolithic client-state changes. |
| 117 | 2026-07-13 | `9c45ae1` | fix(ui): stabilize responsive state and fatal disconnects | **Pending** | Pending functional review and fork-specific port decision. |
| 118 | 2026-07-13 | `bf0c5c9` | fix(ui): prevent stale todo overwrites | **Pending** | Pending functional review and fork-specific port decision. |
| 119 | 2026-07-13 | `35ebcdb` | fix(ui): isolate mount paths and disabled remotes | **Pending** | Pending functional review and fork-specific port decision. |
| 120 | 2026-07-13 | `6a29ddf` | fix(ui): discard stale polling responses | **Pending** | Pending functional review and fork-specific port decision. |
| 121 | 2026-07-13 | `f564761` | fix(auth): require strong public OAuth approval credentials | **Pending** | Pending functional review and fork-specific port decision. |
| 122 | 2026-07-13 | `d3050aa` | fix(audit): serialize trimming and appends | **Implemented (adapted)** | Audit append and retention are serialized with a process-wide lock plus a cross-process lock file; replacement is atomic and both log and lock remain private. |
| 123 | 2026-07-13 | `bfc08df` | fix(remotes): bound invites and validate node identities | **Implemented (adapted)** | The fork-native remote manager already trims and validates 128-character machine names, prunes expired or consumed invites, caps live invites at 1,024 under enrollment and state locks, and removes invites atomically when registration succeeds. Join commands intentionally use the configured canonical base URL instead of trusting a request-derived origin. |
| 124 | 2026-07-13 | `69bb316` | fix(ui): make editor saves atomic and conflict-safe | **Pending** | Pending functional review and fork-specific port decision. |
| 125 | 2026-07-13 | `5d0a5c6` | test(auth): use S256 PKCE in the MCP endpoint probe | **Pending** | Pending functional review and fork-specific port decision. |
| 126 | 2026-07-14 | `4a4b9d2` | fix(ui): reserve F8 for raw terminal mode | **Pending** | Pending functional review and fork-specific port decision. |
| 127 | 2026-07-14 | `d810037` | test(ui): make editor checks portable on Windows | **Pending** | Pending functional review and fork-specific port decision. |
| 128 | 2026-07-14 | `c593612` | fix(auth): enforce scopes and confine native UI token | **Pending** | Pending functional review and fork-specific port decision. |
| 129 | 2026-07-14 | `f416d2b` | fix(files): preserve symlinks and serialize writes | **Pending** | Pending functional review and fork-specific port decision. |
| 130 | 2026-07-14 | `7a3cda8` | fix(ui): bound remote work and unblock event loop | **Pending** | Pending functional review and fork-specific port decision. |
| 131 | 2026-07-14 | `e769485` | fix(ui): serialize state and isolate interactions | **Pending** | Pending functional review and fork-specific port decision. |
| 132 | 2026-07-14 | `edae303` | fix(release): remove rejected OAuth placeholders | **Pending** | Pending functional review and fork-specific port decision. |
| 133 | 2026-07-14 | `f7fd688` | fix(ci): eliminate error annotations | **Pending** | Pending functional review and fork-specific port decision. |
| 134 | 2026-07-14 | `d172ecc` | fix(ci): drain grep subprocess cleanup | **Pending** | Pending functional review and fork-specific port decision. |
| 135 | 2026-07-14 | `8379169` | fix: harden auth downloads and audit logging | **Partial** | Audit serialization and file-share hardening are adapted: immutable private snapshots, no-follow/identity checks, token fingerprints, safe filenames, streaming from an already-open handle, and private durable state. Authentication, search, and Human UI portions remain separate reviews. |
| 136 | 2026-07-14 | `867330f` | fix: make remote transfers transactional | **Implemented (adapted)** | Chunked writes now bind private metadata to the destination and temporary-file identity, account for non-overlapping received ranges, recheck `overwrite=false` at commit, validate final size/hash, and publish with `os.replace`. Directory copies validate/extract in staging and restore the old destination if commit fails. |
| 137 | 2026-07-14 | `1bdb837` | fix: isolate human UI state by machine | **Pending** | Pending functional review and fork-specific port decision. |
| 138 | 2026-07-14 | `51879f9` | fix: persist long-running job results | **Implemented (adapted)** | Tracked jobs now use a private internal runner that durably records combined output, exit code, completion time, and errors; output remains pollable after process exit and restart. |
| 139 | 2026-07-14 | `17ed1e9` | fix: correct MCP safety annotations | **Pending** | Pending functional review and fork-specific port decision. |
| 140 | 2026-07-14 | `c2acf69` | fix: share shell output budget across streams | **Pending** | Pending functional review and fork-specific port decision. |
| 141 | 2026-07-14 | `212a4cb` | fix: sanitize all audit event fields | **Implemented (adapted)** | All `audit()` fields now pass through one recursive redaction and portability boundary, including direct shell, OAuth, download, job, and remote events. |
| 142 | 2026-07-14 | `55ff945` | fix: bound path lock resource usage | **Implemented (adapted)** | Filesystem mutations use a ref-counted in-process path-lock registry that releases unused entries plus a fixed 256-shard cross-process lock set under private state, avoiding unbounded lock growth. |
| 143 | 2026-07-14 | `403e9bb` | docs: document job and transfer limits | **Implemented (adapted)** | Fork documentation and generated configuration describe `max_job_log_bytes` and `max_jobs`, including durable polling and active-job retention semantics. |
| 144 | 2026-07-14 | `afb53ed` | fix: validate remote worker server URLs | **Pending** | Pending functional review and fork-specific port decision. |
| 145 | 2026-07-14 | `20f3861` | Merge pull request #4 from fwerkor/fix/deep-audit-bugs | **Pending** | Pending functional review and fork-specific port decision. |
| 146 | 2026-07-14 | `e106ed4` | fix(ui): normalize invalid token path errors on Windows | **Pending** | Pending functional review and fork-specific port decision. |
| 147 | 2026-07-14 | `d5c7cbb` | fix(jobs): invoke runner correctly from PowerShell | **Implemented (adapted)** | Internal runner argv is quoted per POSIX shell, cmd.exe, or PowerShell, including apostrophes and paths containing spaces; unit coverage locks down PowerShell quoting. |
| 148 | 2026-07-14 | `971688b` | Merge pull request #5 from fwerkor/fix/windows-ci-regressions | **Pending** | Pending functional review and fork-specific port decision. |
| 149 | 2026-07-14 | `41512fb` | fix(security): harden OAuth assets and file shares | **Partial** | The file-share security portion is implemented more strictly with creation-time snapshots, primary/backup transactional state, cross-process locking, digest verification, orphan cleanup, and local/remote session support. OAuth asset and Human UI changes remain separate. |
| 150 | 2026-07-14 | `d5a81b7` | fix(jobs): serialize state and bound retention | **Implemented (adapted)** | The fork serializes job-store transactions with thread and cross-process locks, atomically writes primary and backup stores, and bounds logs and retained terminal jobs without pruning active jobs. |
| 151 | 2026-07-14 | `2319219` | fix(settings): isolate persisted secret reads | **Pending** | Pending functional review and fork-specific port decision. |
| 152 | 2026-07-14 | `557ca1b` | fix(io): preserve PTY input and dedupe lock shards | **Pending** | Pending functional review and fork-specific port decision. |
| 153 | 2026-07-14 | `99b0c1a` | fix(remote): fail permanent errors and keep jobs online | **Implemented (adapted)** | Worker HTTP failures now distinguish transient statuses from permanent client errors, and long-running tool execution sends independent heartbeats so the control server does not mark an active worker offline. |
| 154 | 2026-07-14 | `311f0f1` | fix(transfer): prune temporary artifacts | **Pending** | Pending functional review and fork-specific port decision. |
| 155 | 2026-07-14 | `fca3071` | fix(ui): retry PTY writes under backpressure | **Pending** | Pending functional review and fork-specific port decision. |
| 156 | 2026-07-14 | `4cf053e` | fix(lifecycle): close cleanup edge cases | **Pending** | Pending functional review and fork-specific port decision. |
| 157 | 2026-07-14 | `81be9b1` | test(oauth): use a strong compatibility key | **Pending** | Pending functional review and fork-specific port decision. |
| 158 | 2026-07-14 | `3deee21` | chore(vscode): update vulnerable packaging dependencies | **Pending** | Pending functional review and fork-specific port decision. |
| 159 | 2026-07-14 | `7864dff` | fix(ui): accept queued ConPTY writes | **Pending** | Pending functional review and fork-specific port decision. |
| 160 | 2026-07-14 | `21170ea` | fix(vscode): await process tree shutdown | **Pending** | Pending functional review and fork-specific port decision. |
| 161 | 2026-07-14 | `f26d826` | fix(http): bound inbound request bodies | **Implemented (adapted)** | A shared ASGI middleware protects REST, MCP, OAuth, download, and remote HTTP routes. It rejects oversized declared lengths before reading, counts actual chunked/no-length bodies, replays accepted messages, preserves live receive for streaming, authenticates protected routes first, and audits metadata without body contents. |
| 162 | 2026-07-14 | `579fc2e` | Merge pull request #6 from fwerkor/fix/deep-audit-followups | **Pending** | Pending functional review and fork-specific port decision. |
| 163 | 2026-07-14 | `74d90e3` | fix(transfer): stream remote files over HTTP | **Not adopted** | The fork does not add upstream HTTP transfer endpoints. It keeps the authenticated remote-worker control channel and bounded explicit-session chunk RPCs while adopting the transactional validation semantics. |
| 164 | 2026-07-14 | `5f8404e` | test(transfer): cover streamed remote copies | **Implemented (adapted)** | Coverage spans local/local, local/remote, remote/local, same- and cross-machine remote copies, multi-chunk checksums, offset/EOF validation, overwrite races, directory staging, and real remote-worker E2E without introducing an HTTP transfer protocol. |
| 165 | 2026-07-14 | `6e90650` | Fix interrupted remote downloads | **Implemented (adapted)** | Cancellation now catches `BaseException`, shields best-effort destination abort, and cleans source and destination archive scratch paths even when the caller task is cancelled. |
| 166 | 2026-07-14 | `e08d27e` | Harden persistent job recovery | **Implemented (adapted)** | Job metadata recovers from a valid backup, refuses silent reset when both copies are corrupt, migrates supported legacy stores, and reconciles interrupted lifecycle states. |
| 167 | 2026-07-14 | `d869478` | Synchronize remote worker registry | **Implemented (adapted)** | The fork serializes registry, token, queue, pending-job, rename, revoke, heartbeat, and result state behind one manager lock, with per-job worker ownership checks. |
| 168 | 2026-07-14 | `99f5af3` | Harden transfer and ConPTY cleanup | **Partial** | Download and transfer cleanup portions are adapted: private immutable snapshots, stale/interrupted artifact cleanup, metadata-bound chunk writes, staged directory rollback, and post-commit cleanup reporting. ConPTY-specific changes remain a separate Windows terminal review. |
| 169 | 2026-07-14 | `1bfaba5` | fix: allow shell timeout cleanup before watchdog | **Pending** | Pending functional review and fork-specific port decision. |
| 170 | 2026-07-14 | `eac80f6` | Remove unused dynamic agent bridge | **Not adopted** | The fork's dynamic Agent Bridge is active, tested, and part of its product direction, so upstream removal is intentionally not ported. |
| 171 | 2026-07-14 | `bbd5c67` | Fix Windows cleanup regressions | **Pending** | Pending functional review and fork-specific port decision. |
| 172 | 2026-07-14 | `d3bd5be` | Bundle tmux for Linux persistent shells | **Pending** | Pending functional review and fork-specific port decision. |
| 173 | 2026-07-14 | `a59fce6` | Fix bundled tmux tests on Windows | **Pending** | Pending functional review and fork-specific port decision. |
| 174 | 2026-07-15 | `a512008` | security: harden MCP sessions and remote results | **Pending** | Pending functional review and fork-specific port decision. |
| 175 | 2026-07-15 | `0b043d7` | fix: serialize job and shell lifecycle transitions | **Implemented (adapted)** | Start, stop, and retry use persisted transitional states plus operation ids, with rollback and stale-transition recovery around the fork's explicit session and shell APIs. |
| 176 | 2026-07-15 | `7f9daf1` | fix: handle remote paths and file action types | **Pending** | Pending functional review and fork-specific port decision. |
| 177 | 2026-07-15 | `2f7bb3b` | guide agents through fixed skill tools | **Implemented (adapted)** | Tool descriptions guide callers through `list_agent_skills`, `activate_agent_skill`, then `read_agent_skill_file`; dynamic bridge compatibility remains available. |
| 178 | 2026-07-15 | `af2503e` | fix: submit native Windows shell commands with CRLF | **Pending** | Pending functional review and fork-specific port decision. |
| 179 | 2026-07-15 | `e768b27` | fix(ci): authenticate OAuth MCP probes before connecting | **Pending** | Pending functional review and fork-specific port decision. |
| 180 | 2026-07-15 | `479138e` | fix: harden local execution and interfaces | **Pending** | Pending functional review and fork-specific port decision. |
| 181 | 2026-07-15 | `33a30ae` | fix: make remote operations transactional | **Implemented (adapted)** | Remote calls reserve capacity and ownership transactionally, clean pending state on timeout or cancellation, skip cancelled queued jobs, reject cross-worker results, and bound in-flight jobs per worker. |
| 182 | 2026-07-15 | `ae68cd8` | test: cover comprehensive bug audit regressions | **Pending** | Pending functional review and fork-specific port decision. |
| 183 | 2026-07-15 | `69f9b27` | fix: pass job environment policy explicitly | **Implemented (adapted)** | The runner uses the fork's existing centralized `_subprocess_env` policy, and its parent persistent shell is launched with the same filtered environment, avoiding a second configurable policy surface. |
| 184 | 2026-07-15 | `64d2e52` | fix: encode job policy arguments for powershell | **Implemented (adapted)** | Runner arguments are shell-neutrally structured and PowerShell-quoted as individual argv values, so no JSON policy payload needs shell-specific encoding in the fork. |
| 185 | 2026-07-15 | `892e829` | Merge pull request #7 from fwerkor/fix/comprehensive-bug-audit | **Pending** | Pending functional review and fork-specific port decision. |
| 186 | 2026-07-15 | `9f317eb` | refactor: unify local and remote tool execution | **Pending** | Pending functional review and fork-specific port decision. |
| 187 | 2026-07-15 | `dff7644` | chore: align auth and clients with compact tools | **Pending** | Pending functional review and fork-specific port decision. |
| 188 | 2026-07-15 | `47fe235` | test: lock down the compact tool contract | **Pending** | Pending functional review and fork-specific port decision. |
| 189 | 2026-07-15 | `f0abf5c` | docs: generate tool reference from schemas | **Pending** | Pending functional review and fork-specific port decision. |
| 190 | 2026-07-15 | `2952132` | docs: update compact tool workflows | **Pending** | Pending functional review and fork-specific port decision. |
| 191 | 2026-07-15 | `06448ae` | docs: remove obsolete tool names from localized pages | **Pending** | Pending functional review and fork-specific port decision. |
| 192 | 2026-07-15 | `a04892e` | Merge pull request #8 from fwerkor/refactor/compact-tool-surface | **Pending** | Pending functional review and fork-specific port decision. |
| 193 | 2026-07-15 | `77c5de9` | ci: enforce combined coverage and reclaim Docker disk | **Pending** | Pending functional review and fork-specific port decision. |
| 194 | 2026-07-15 | `fbc3a91` | fix: preserve explicit fallback settings updates | **Pending** | Pending functional review and fork-specific port decision. |
| 195 | 2026-07-15 | `c3ef371` | test: cover persistent runtime recovery paths | **Implemented (adapted)** | Unit tests cover store recovery, migration, retention, completed output, failed starts, and interrupted start/retry transitions; stdio, HTTP, MCP, and remote-worker E2E paths exercise the durable job flow. |
| 196 | 2026-07-15 | `8a2a92a` | test: cover core API auth and Human UI branches | **Pending** | Pending functional review and fork-specific port decision. |
| 197 | 2026-07-15 | `ef9771f` | test: cover tool surface storage and skill safety | **Implemented (adapted)** | Unit coverage now exercises Skill safety and bounds, and an integration test installs the pinned real `LeonardNJU/code-humanizer` repository through Git before using the HTTP tool surface. |
| 198 | 2026-07-15 | `3fbc891` | test: add real remote worker end-to-end coverage | **Pending** | Pending functional review and fork-specific port decision. |
| 199 | 2026-07-15 | `574515d` | test: cover UI clients and extension process lifecycle | **Pending** | Pending functional review and fork-specific port decision. |
| 200 | 2026-07-15 | `b4e7fdc` | ci: enforce near-complete coverage and binary smoke builds | **Pending** | Pending functional review and fork-specific port decision. |
| 201 | 2026-07-15 | `06eb86e` | test: make expanded coverage suite cross-platform | **Pending** | Pending functional review and fork-specific port decision. |
| 202 | 2026-07-15 | `aca8ae8` | test: use platform-specific TUI sidecar name | **Pending** | Pending functional review and fork-specific port decision. |
| 203 | 2026-07-15 | `c649f27` | ci: avoid duplicate feature branch matrices | **Pending** | Pending functional review and fork-specific port decision. |
| 204 | 2026-07-15 | `119975a` | Merge pull request #9 from fwerkor/test/near-complete-coverage | **Pending** | Pending functional review and fork-specific port decision. |
| 205 | 2026-07-16 | `6ab0d2a` | feat: persist and manage remote workers | **Partial** | Worker registration, identity persistence, resume, rename, revoke, inventory, and primary/backup control-side state are implemented. Upstream systemd/launchd service installation and management are intentionally deferred to a separate fork-specific lifecycle design. |
| 206 | 2026-07-16 | `44b3692` | fix: harden persisted worker lifecycle | **Partial** | Persisted identity, worker runtime environment setup, strict registry recovery, clean CLI failure handling, and restart resume are hardened. User-service install/start/stop/update behavior remains a separate follow-up. |
| 207 | 2026-07-16 | `21571b4` | test: handle JSON-escaped Windows paths | **Pending** | Pending functional review and fork-specific port decision. |
| 208 | 2026-07-16 | `2051a53` | fix(worker): secure connect and prepare runtime on start | **Partial** | Worker server URLs are restricted to absolute HTTP(S), runtime paths are prepared before normal settings load, and credentials stay in the persisted identity rather than result payloads. Upstream launcher installation/re-exec service workflow is not adopted in this batch. |
| 209 | 2026-07-16 | `789520b` | Merge pull request #11 from fwerkor/fix/remote-worker-persist-lifecycle | **Superseded by reviewed commits** | Merge-only commit; persistence, runtime preparation, and service-lifecycle decisions are recorded on the underlying remote-worker commits. |
| 210 | 2026-07-16 | `f837152` | fix: harden compact tool contracts | **Pending** | Pending functional review and fork-specific port decision. |
| 211 | 2026-07-16 | `b918d18` | docs: align examples with compact tools | **Pending** | Pending functional review and fork-specific port decision. |
| 212 | 2026-07-16 | `2aa1a31` | Merge pull request #13 from fwerkor/fix/compact-tool-contracts | **Pending** | Pending functional review and fork-specific port decision. |
| 213 | 2026-07-16 | `cd7d96f` | feat: add native image viewing tool | **Implemented (adapted)** | Added MCP-only `view_image(session_id, path)` with native `ImageContent`, explicit local/remote session dispatch, format magic checks, a 20 MiB bound, and validated remote transfer chunks instead of upstream's optional machine parameter. |
| 214 | 2026-07-16 | `d592468` | Merge pull request #15 from fwerkor/feat/view-image | **Superseded by reviewed commits** | Merge-only commit; the native image-viewing decision is recorded on the underlying feature commit. |
| 215 | 2026-07-16 | `b4f87e2` | deslop: remove tool wrapper boilerplate (#6) | **Pending** | Pending functional review and fork-specific port decision. |
| 216 | 2026-07-16 | `7395ea3` | deslop: share success envelopes (#1) | **Pending** | Pending functional review and fork-specific port decision. |
| 217 | 2026-07-16 | `aa3bc2b` | ci: use 90 percent module coverage floor | **Pending** | Pending functional review and fork-specific port decision. |
| 218 | 2026-07-16 | `0a7c983` | deslop: simplify conpty tail trimming (#6) | **Pending** | Pending functional review and fork-specific port decision. |
| 219 | 2026-07-16 | `ee0e77d` | deslop: share transfer chunk writes (#1) — 2 instances | **Pending** | Pending functional review and fork-specific port decision. |
| 220 | 2026-07-16 | `31eea53` | deslop: remove runtime import indirection (#9) — 4 instances | **Pending** | Pending functional review and fork-specific port decision. |
| 221 | 2026-07-16 | `d702368` | deslop: split MCP registration by domain (#6) — 11 groups | **Pending** | Pending functional review and fork-specific port decision. |
| 222 | 2026-07-16 | `c49c3b1` | deslop: split remote worker dispatch (#6) — 7 domains | **Pending** | Pending functional review and fork-specific port decision. |
| 223 | 2026-07-16 | `7f02ae2` | deslop: split REST route assembly (#6) — 9 groups | **Pending** | Pending functional review and fork-specific port decision. |
| 224 | 2026-07-16 | `eba3f7b` | deslop: remove thread pass-through wrappers (#6) — 3 instances | **Pending** | Pending functional review and fork-specific port decision. |
| 225 | 2026-07-16 | `a25fc49` | deslop: centralize shell argument policy (#1) — 2 implementations | **Pending** | Pending functional review and fork-specific port decision. |
| 226 | 2026-07-16 | `f547e5d` | deslop: share packed directory transfer (#1) — 2 implementations | **Pending** | Pending functional review and fork-specific port decision. |
| 227 | 2026-07-16 | `94111d8` | deslop: remove image thread wrapper calls (#6) — 4 instances | **Pending** | Pending functional review and fork-specific port decision. |
| 228 | 2026-07-16 | `193a849` | Merge pull request #14 from fwerkor/refactor/code-humanizer | **Pending** | Pending functional review and fork-specific port decision. |
| 229 | 2026-07-17 | `e4bfdec` | Polish OAuth authorization page | **Pending** | Pending functional review and fork-specific port decision. |
| 230 | 2026-07-17 | `41ea83f` | fix: make OpenTUI usable on narrow screens | **Pending** | Pending functional review and fork-specific port decision. |
| 231 | 2026-07-17 | `250cb4f` | fix: add mobile WebUI terminal controls | **Pending** | Pending functional review and fork-specific port decision. |
| 232 | 2026-07-17 | `7f6c146` | fix: preserve compact nav at 47 columns | **Pending** | Pending functional review and fork-specific port decision. |
| 233 | 2026-07-17 | `d7643f7` | Merge pull request #16 from fwerkor/ui/oauth-page-polish | **Pending** | Pending functional review and fork-specific port decision. |
| 234 | 2026-07-17 | `426c013` | feat(ui): add distinct TUI screen themes | **Pending** | Pending functional review and fork-specific port decision. |
| 235 | 2026-07-17 | `f4e3966` | style(ui): align WebUI terminal palette | **Pending** | Pending functional review and fork-specific port decision. |
| 236 | 2026-07-17 | `6ac77bc` | fix(ui): remove shortcut labels from top navigation | **Pending** | Pending functional review and fork-specific port decision. |
| 237 | 2026-07-17 | `4cb27aa` | test(ui): update smoke labels for simplified navigation | **Pending** | Pending functional review and fork-specific port decision. |
| 238 | 2026-07-17 | `4342afc` | Merge pull request #17 from fwerkor/ui/tui-color-polish | **Pending** | Pending functional review and fork-specific port decision. |
| 239 | 2026-07-17 | `bf94284` | feat(downloads): support inline file links | **Implemented (adapted)** | `create_file_link(..., inline=true)` now opts into inline browser rendering while attachment remains the default. Links are explicit-session, immutable snapshots and support both local and remote sources. |
| 240 | 2026-07-17 | `458917d` | test(windows): allow slower native shell startup | **Pending** | Pending functional review and fork-specific port decision. |
| 241 | 2026-07-17 | `bb39e83` | fix(downloads): sandbox inline responses | **Implemented (adapted)** | Inline responses add `Content-Security-Policy: sandbox`; all snapshot responses add `nosniff`, `no-referrer`, private no-store caching, safe content disposition, and streaming from a validated open file descriptor. |
| 242 | 2026-07-17 | `b835b2c` | chore(release): bump version to 3.0.1 | **Pending** | Pending functional review and fork-specific port decision. |
| 243 | 2026-07-17 | `31d2b7b` | fix(downloads): infer MIME from display filename | **Implemented (adapted)** | MIME inference uses the original source filename first, then the optional browser display filename, and finally `application/octet-stream`. |
| 244 | 2026-07-17 | `c684296` | Merge pull request #18 from fwerkor/feat/inline-file-links | **Superseded by reviewed commits** | Merge-only commit; inline disposition, sandboxing, and MIME behavior are recorded on the underlying commits. |
| 245 | 2026-07-17 | `2e028d1` | docs(config): keep one canonical example | **Pending** | Pending functional review and fork-specific port decision. |
| 246 | 2026-07-17 | `834fee5` | fix(compose): forward canonical env settings | **Pending** | Pending functional review and fork-specific port decision. |
| 247 | 2026-07-17 | `a15c78d` | Merge pull request #19 from fwerkor/chore/single-config-example | **Pending** | Pending functional review and fork-specific port decision. |
| 248 | 2026-07-17 | `3f89325` | feat(webui): render inline terminal images | **Pending** | Pending functional review and fork-specific port decision. |
| 249 | 2026-07-17 | `2d49704` | feat(ui): advertise inline image protocols | **Pending** | Pending functional review and fork-specific port decision. |
| 250 | 2026-07-17 | `ad7d89a` | fix(webui): align image addon with xterm 5.5 | **Pending** | Pending functional review and fork-specific port decision. |
| 251 | 2026-07-17 | `eff6e65` | Merge pull request #20 from fwerkor/feat/webui-inline-images | **Pending** | Pending functional review and fork-specific port decision. |
| 252 | 2026-07-17 | `054bcc5` | fix(oauth): allow 8-character admin PINs | **Pending** | Pending functional review and fork-specific port decision. |
| 253 | 2026-07-17 | `5b174b7` | fix(auth): persist OAuth clients and grant full access | **Pending** | Pending functional review and fork-specific port decision. |
| 254 | 2026-07-17 | `a86f367` | fix(auth): preserve scoped tokens and bound registrations | **Pending** | Pending functional review and fork-specific port decision. |
| 255 | 2026-07-17 | `9137843` | Merge pull request #21 from fwerkor/fix/oauth-pin-min-length-8 | **Pending** | Pending functional review and fork-specific port decision. |
| 256 | 2026-07-17 | `d5f9b73` | build(ui): stage OpenTUI for standalone embedding | **Pending** | Pending functional review and fork-specific port decision. |
| 257 | 2026-07-17 | `b6c8618` | fix(binary): activate embedded OpenTUI runtime | **Pending** | Pending functional review and fork-specific port decision. |
| 258 | 2026-07-17 | `d29d2cb` | chore(ui): ignore staged native runtime | **Pending** | Pending functional review and fork-specific port decision. |
| 259 | 2026-07-17 | `35ca8b7` | fix(docker): wire and verify bundled human UI runtime | **Pending** | Pending functional review and fork-specific port decision. |
| 260 | 2026-07-17 | `88fce86` | test(ui): add standalone and Docker runtime smoke | **Pending** | Pending functional review and fork-specific port decision. |
| 261 | 2026-07-17 | `d032e8f` | ci(ui): verify standalone and Docker UI runtimes | **Pending** | Pending functional review and fork-specific port decision. |
| 262 | 2026-07-17 | `8e4ef5a` | fix(binary): embed compressed TUI payload | **Pending** | Pending functional review and fork-specific port decision. |
| 263 | 2026-07-17 | `a3abb41` | fix(binary): unpack embedded TUI at startup | **Pending** | Pending functional review and fork-specific port decision. |
| 264 | 2026-07-17 | `c628d9c` | ci(ui): retain PyInstaller failure logs | **Pending** | Pending functional review and fork-specific port decision. |
| 265 | 2026-07-17 | `029fa6f` | docs(ui): describe embedded standalone and Docker runtimes | **Pending** | Pending functional review and fork-specific port decision. |
| 266 | 2026-07-17 | `b0d8547` | ci(ui): report temporary macOS build diagnostics | **Pending** | Pending functional review and fork-specific port decision. |
| 267 | 2026-07-17 | `0f21efd` | ci(ui): capture standalone runtime diagnostics | **Pending** | Pending functional review and fork-specific port decision. |
| 268 | 2026-07-17 | `10347a6` | ci(ui): expose failure summaries through artifacts | **Pending** | Pending functional review and fork-specific port decision. |
| 269 | 2026-07-17 | `05039a1` | ci(ui): add temporary cross-platform diagnostics | **Pending** | Pending functional review and fork-specific port decision. |
| 270 | 2026-07-17 | `00f27f4` | test(ui): terminate Windows one-file process trees reliably | **Pending** | Pending functional review and fork-specific port decision. |
| 271 | 2026-07-17 | `7d44444` | ci(ui): keep final cross-platform runtime coverage | **Pending** | Pending functional review and fork-specific port decision. |
| 272 | 2026-07-17 | `1109c4e` | ci(ui): remove temporary diagnostic workflow | **Pending** | Pending functional review and fork-specific port decision. |
| 273 | 2026-07-17 | `d0d7319` | ci: apply cross-workflow Bash compatibility patch | **Pending** | Pending functional review and fork-specific port decision. |
| 274 | 2026-07-17 | `41ada78` | ci: run one-time Bash compatibility patch on PR | **Pending** | Pending functional review and fork-specific port decision. |
| 275 | 2026-07-17 | `b1bc388` | ci: make one-time Bash patch line-based | **Pending** | Pending functional review and fork-specific port decision. |
| 276 | 2026-07-17 | `ce71216` | ci: export Bash-compatible workflow patches | **Pending** | Pending functional review and fork-specific port decision. |
| 277 | 2026-07-17 | `786ddf4` | fix(ui): quote embedded TUI command paths | **Pending** | Pending functional review and fork-specific port decision. |
| 278 | 2026-07-17 | `75ed15e` | fix(ci): support macOS Bash 3.2 in binary builds | **Pending** | Pending functional review and fork-specific port decision. |
| 279 | 2026-07-17 | `205a299` | Merge pull request #22 from fwerkor/fix/embedded-ui-runtime | **Pending** | Pending functional review and fork-specific port decision. |
| 280 | 2026-07-17 | `a33453b` | Update pyproject.toml | **Pending** | Pending functional review and fork-specific port decision. |
| 281 | 2026-07-17 | `ca2c402` | Merge pull request #23 from fwerkor/fwerkor-patch-1 | **Pending** | Pending functional review and fork-specific port decision. |
| 282 | 2026-07-17 | `75cbf95` | Fix job store migration and startup durability | **Implemented (adapted)** | Store v1 migration, primary/backup recovery, pre-launch reservation, durable starting state, startup rollback, and interrupted-start recovery are implemented in the fork job service. |
| 283 | 2026-07-17 | `0447f96` | Cover job startup failure paths | **Implemented (adapted)** | Tests verify shell-launch failure is persisted as a terminal failed job and interrupted starts recover only when a matching shell remains active. |
| 284 | 2026-07-17 | `7b7e7c9` | Merge pull request #24 from fwerkor/fix/job-store-migration | **Superseded by reviewed commits** | Merge-only commit; migration, startup durability, and failure-path decisions are recorded on the underlying job commits. |
| 285 | 2026-07-17 | `605f0c2` | fix(audit): preserve tool inputs without redaction | **Not adopted** | The fork intentionally keeps best-effort credential redaction. Non-sensitive inputs remain complete within the event budget, but raw tokens, approval PINs, authorization headers, and download URLs are not retained. |
| 286 | 2026-07-17 | `e3fe41b` | Merge pull request #25 from fwerkor/fix/audit-no-redaction | **Superseded by reviewed commits** | Merge-only commit for the upstream no-redaction direction, which the fork intentionally does not adopt. |
| 287 | 2026-07-17 | `005b98f` | Fix WebUI mouse and terminal shortcuts | **Pending** | Pending functional review and fork-specific port decision. |
| 288 | 2026-07-17 | `e82a76b` | Cover human UI mouse interactions | **Pending** | Pending functional review and fork-specific port decision. |
| 289 | 2026-07-17 | `77ab1e2` | Rebuild WebUI assets with CI Bun | **Pending** | Pending functional review and fork-specific port decision. |
| 290 | 2026-07-17 | `e2d5ac6` | Stabilize terminal creation browser smoke | **Pending** | Pending functional review and fork-specific port decision. |
| 291 | 2026-07-17 | `584cfa6` | ci: remove redundant UI runtime workflow | **Pending** | Pending functional review and fork-specific port decision. |
| 292 | 2026-07-17 | `eee29f3` | Merge pull request #26 from fwerkor/fix/webui-tui-input | **Pending** | Pending functional review and fork-specific port decision. |
| 293 | 2026-07-17 | `65a09c6` | fix: recycle idle MCP sessions sooner | **Pending** | Pending functional review and fork-specific port decision. |
| 294 | 2026-07-17 | `b4f495d` | fix: recycle MCP sessions after three minutes | **Pending** | Pending functional review and fork-specific port decision. |
| 295 | 2026-07-17 | `a3defb6` | Merge pull request #28 from fwerkor/fix/mcp-session-retention | **Pending** | Pending functional review and fork-specific port decision. |
| 296 | 2026-07-17 | `347db8e` | fix(ui): consolidate audit tool calls | **Split follow-up** | Audit-call consolidation and its query model are coupled to the deferred Human UI. Backend retention keeps explicit start/end pairs. |
| 297 | 2026-07-17 | `f9940b0` | test: cover audit call consolidation | **Split follow-up** | These tests target the deferred Human UI audit aggregation rather than the fork JSONL writer. |
| 298 | 2026-07-17 | `287cd61` | Merge pull request #27 from fwerkor/fix/audit-ui-consolidation | **Superseded by reviewed commits** | Merge-only commit for the deferred Human UI audit consolidation. |
| 299 | 2026-07-17 | `27e6d35` | chore: bump version to 3.0.3 | **Pending** | Pending functional review and fork-specific port decision. |
| 300 | 2026-07-17 | `1278272` | Merge pull request #29 from fwerkor/release/v3.0.3 | **Pending** | Pending functional review and fork-specific port decision. |
| 301 | 2026-07-17 | `ad1a6d5` | fix(ui): render image previews in files pane | **Split follow-up** | This is a Human UI files-pane preview feature, not the MCP-native viewer. It remains grouped with the later WebUI/TUI migration. |
| 302 | 2026-07-18 | `41407b8` | fix: keep runtime version in sync with releases | **Pending** | Pending functional review and fork-specific port decision. |
| 303 | 2026-07-17 | `7ad4d84` | feat(skills): support multiple registry sources | **Split follow-up** | A global project/managed/global registry is not ported directly. Session workdir and remote-worker scoped Skill/MCP lookup needs a fork-specific design on top of explicit sessions. |
| 304 | 2026-07-17 | `e3206a0` | fix(skills): validate rooted paths portably | **Implemented (adapted)** | Portable rooted/name/path validation is implemented without adopting upstream's multi-source registry API. |
| 305 | 2026-07-18 | `4c61d21` | fix(ui): correct image preview supersampling dimensions | **Split follow-up** | Supersampling dimensions belong to the deferred Human UI image-preview implementation. |
| 306 | 2026-07-18 | `8bc1d9a` | test(ui): verify image preview cell mapping | **Split follow-up** | UI cell-mapping tests become relevant only when the fork ports the Human UI files-pane preview. |
| 307 | 2026-07-18 | `6666332` | Merge pull request #30 from fwerkor/fix/files-image-preview | **Superseded by reviewed commits** | Merge-only commit for the deferred Human UI preview fixes; underlying commits remain explicit follow-ups. |
| 308 | 2026-07-18 | `42e0480` | Merge branch 'main' into feat/multi-source-skills | **Superseded by reviewed commits** | Merge-only commit; functional decisions are recorded on the underlying Skill commits. |
| 309 | 2026-07-18 | `3746dbd` | Merge branch 'main' into fix/version-consistency | **Pending** | Pending functional review and fork-specific port decision. |
| 310 | 2026-07-18 | `1ab1b83` | Merge pull request #32 from fwerkor/feat/multi-source-skills | **Superseded by reviewed commits** | Merge-only commit; multi-source behavior remains a session-scoped follow-up while portable validation was adapted. |
| 311 | 2026-07-18 | `e808149` | Merge branch 'main' into fix/version-consistency | **Pending** | Pending functional review and fork-specific port decision. |
| 312 | 2026-07-18 | `1834f9c` | test: avoid hard-coded CLI version assertions | **Pending** | Pending functional review and fork-specific port decision. |
| 313 | 2026-07-18 | `bc706c4` | Merge branch 'main' into fix/version-consistency-ci | **Pending** | Pending functional review and fork-specific port decision. |
| 314 | 2026-07-18 | `9c1f323` | Merge pull request #33 from fwerkor/fix/version-consistency-ci | **Pending** | Pending functional review and fork-specific port decision. |
| 315 | 2026-07-18 | `cf6b4e5` | chore: bump version to 3.0.4 | **Pending** | Pending functional review and fork-specific port decision. |
| 316 | 2026-07-18 | `01c37f2` | Merge pull request #34 from fwerkor/release/v3.0.4 | **Pending** | Pending functional review and fork-specific port decision. |
| 317 | 2026-07-18 | `46d3cde` | revert: restore original PR #31 contribution path | **Pending** | Pending functional review and fork-specific port decision. |
| 318 | 2026-07-18 | `e4f4ae5` | fix: keep version-agnostic CLI assertion during revert | **Pending** | Pending functional review and fork-specific port decision. |
| 319 | 2026-07-18 | `2176586` | Merge pull request #35 from fwerkor/revert/pr33-for-original-contributor | **Pending** | Pending functional review and fork-specific port decision. |
| 320 | 2026-07-18 | `7d60caa` | fix(release): ship standalone UI as one executable | **Pending** | Pending functional review and fork-specific port decision. |
| 321 | 2026-07-18 | `3ad2a58` | fix(oauth): reuse matching public clients | **Implemented (adapted)** | Dynamic registration now uses a canonical client-name and redirect-URI-set key, prefers approved clients and then the oldest pending match, and serializes prune, reuse lookup, capacity enforcement, id allocation, and insertion. The split HTTP adapter returns `200` with `reused=true` for matches and `201` with `reused=false` for new clients; approved matches remain reusable after persisted-state reload. |
| 322 | 2026-07-18 | `3ae1338` | fix(audit): preserve complete call payloads | **Implemented (adapted)** | Non-sensitive call inputs, outputs, and nested errors are retained inline up to `max_audit_event_bytes`; oversized payloads become explicitly marked bounded previews instead of unbounded records. |
| 323 | 2026-07-18 | `07f4885` | fix(ui): keep Escape available in fullscreen | **Pending** | Pending functional review and fork-specific port decision. |
| 324 | 2026-07-18 | `c9b6de9` | Merge pull request #37 from fwerkor/fix/embed-opentui-runtime | **Pending** | Pending functional review and fork-specific port decision. |
| 325 | 2026-07-18 | `dc4b0b1` | Merge branch 'main' into fix/webui-oauth-client-reuse | **Superseded by reviewed commits** | Merge-only integration commit. The OAuth registration behavior is covered by `3ad2a58`; unrelated mainline changes remain tracked under their own entries. |
| 326 | 2026-07-18 | `1c4e1ee` | Merge pull request #38 from fwerkor/fix/webui-oauth-client-reuse | **Superseded by reviewed commits** | Merge-only completion of the public-client reuse change reviewed and implemented under `3ad2a58`. |
| 327 | 2026-07-18 | `b6e84c8` | Merge branch 'main' into fix/webui-fullscreen-escape | **Pending** | Pending functional review and fork-specific port decision. |
| 328 | 2026-07-18 | `ab3d9c9` | Merge branch 'main' into fix/audit-full-payloads | **Pending** | Pending functional review and fork-specific port decision. |
| 329 | 2026-07-18 | `5d7e11d` | fix(ui): make terminal output scrollable | **Pending** | Pending functional review and fork-specific port decision. |
| 330 | 2026-07-18 | `013661c` | fix(audit): harden external payload retention | **Partial** | Portable values, binary summaries, event byte limits, atomic retention, and private permissions are implemented. The upstream gzip payload side store is deferred because the fork has no audit-detail UI or query API that consumes it. |
| 331 | 2026-07-18 | `3438a32` | test(audit): make permission assertion portable | **Implemented (adapted)** | Permission assertions are platform-aware, while POSIX tests verify both the JSONL log and lock file use mode `0600`. |
| 332 | 2026-07-18 | `3db979b` | fix(ui): support mouse wheel navigation | **Pending** | Pending functional review and fork-specific port decision. |
| 333 | 2026-07-18 | `fc61348` | fix(ui): stop file preview reload loop | **Pending** | Pending functional review and fork-specific port decision. |
| 334 | 2026-07-18 | `88646d5` | test(audit): cover detail validation paths | **Implemented (adapted)** | Tests cover cycles, binary values, non-finite floats, unsupported objects, nested errors, oversized events, irreversible fingerprints, and secret redaction. |
| 335 | 2026-07-18 | `d3bc56b` | feat(ui): make footer shortcuts clickable | **Pending** | Pending functional review and fork-specific port decision. |
| 336 | 2026-07-18 | `d8976a1` | cleanup(ui): remove Yazi packaging and references | **Pending** | Pending functional review and fork-specific port decision. |
| 337 | 2026-07-18 | `dc8cad0` | Merge pull request #43 from fwerkor/fix/file-preview-reload | **Pending** | Pending functional review and fork-specific port decision. |
| 338 | 2026-07-18 | `527a18b` | Merge branch 'main' into cleanup/remove-yazi | **Pending** | Pending functional review and fork-specific port decision. |
| 339 | 2026-07-18 | `902f447` | Merge pull request #45 from fwerkor/cleanup/remove-yazi | **Pending** | Pending functional review and fork-specific port decision. |
| 340 | 2026-07-18 | `4c25a66` | Merge branch 'main' into feat/clickable-footer-shortcuts | **Pending** | Pending functional review and fork-specific port decision. |
| 341 | 2026-07-18 | `08dfbc6` | Merge pull request #46 from fwerkor/feat/clickable-footer-shortcuts | **Pending** | Pending functional review and fork-specific port decision. |
| 342 | 2026-07-18 | `781da0d` | Merge remote-tracking branch 'origin/main' into fix/audit-full-payloads | **Pending** | Pending functional review and fork-specific port decision. |
| 343 | 2026-07-18 | `4815a5e` | fix(ui): decouple fullscreen resize from keyboard lock | **Pending** | Pending functional review and fork-specific port decision. |
| 344 | 2026-07-18 | `f289f07` | Merge remote-tracking branch 'origin/main' into fix/webui-fullscreen-escape | **Pending** | Pending functional review and fork-specific port decision. |
| 345 | 2026-07-18 | `aa16c7a` | Merge remote-tracking branch 'origin/main' into fix/terminal-output-scrolling | **Pending** | Pending functional review and fork-specific port decision. |
| 346 | 2026-07-18 | `b0fef20` | Merge remote-tracking branch 'origin/main' into fix/webui-mouse-wheel | **Pending** | Pending functional review and fork-specific port decision. |
| 347 | 2026-07-18 | `763aa28` | test(ui): assert raw mode state directly | **Pending** | Pending functional review and fork-specific port decision. |
| 348 | 2026-07-18 | `16cb4c6` | fix(audit): keep payloads portable and calls paired | **Implemented (adapted)** | Audit values are converted to portable JSON and retention groups tool-call start/end rows by `call_id`, preserving completed pairs without adopting the upstream external payload store. |
| 349 | 2026-07-18 | `e0bcdbf` | feat(ui): add mouse navigation to files | **Pending** | Pending functional review and fork-specific port decision. |
| 350 | 2026-07-18 | `85e11a7` | fix(ui): preserve terminal history viewport | **Pending** | Pending functional review and fork-specific port decision. |
| 351 | 2026-07-18 | `d45d379` | fix(ui): require completed file clicks | **Pending** | Pending functional review and fork-specific port decision. |
| 352 | 2026-07-18 | `65bd9b3` | test(audit): cover retention edge paths | **Implemented (adapted)** | Retention tests cover bounded log size, completed pair integrity, concurrent writers, and atomic private replacement. |
| 353 | 2026-07-18 | `4ce23cc` | fix(audit): collapse tool call lifecycle rows | **Not adopted** | Collapsing start/end rows into one lifecycle record is a Human UI optimization. The fork keeps explicit paired events, which are simpler for JSONL streaming and existing consumers. |
| 354 | 2026-07-18 | `8af939a` | Merge pull request #47 from fwerkor/feat/files-mouse-navigation | **Pending** | Pending functional review and fork-specific port decision. |
| 355 | 2026-07-18 | `7936891` | feat(ui): show remote LSM versions | **Pending** | Pending functional review and fork-specific port decision. |
| 356 | 2026-07-18 | `a9f1b94` | fix(ui): freeze terminal history while scrolled | **Pending** | Pending functional review and fork-specific port decision. |
| 357 | 2026-07-18 | `45ce451` | fix(ui): preserve image preview proportions | **Pending** | Pending functional review and fork-specific port decision. |
| 358 | 2026-07-18 | `d35f1b0` | fix(ui): let WebUI use large viewports | **Pending** | Pending functional review and fork-specific port decision. |
| 359 | 2026-07-18 | `94b537b` | Merge pull request #48 from fwerkor/feat/remotes-lsm-version | **Pending** | Pending functional review and fork-specific port decision. |
| 360 | 2026-07-18 | `7fef85d` | Merge branch 'main' into fix/image-preview-layout | **Pending** | Pending functional review and fork-specific port decision. |
| 361 | 2026-07-18 | `0067171` | Merge branch 'main' into fix/webui-fluid-size | **Pending** | Pending functional review and fork-specific port decision. |
| 362 | 2026-07-18 | `59d9445` | feat(ui): add responsive system dashboard | **Pending** | Pending functional review and fork-specific port decision. |
| 363 | 2026-07-18 | `9d8eaa7` | chore: prepare PR 31 compatibility merge | **Pending** | Pending functional review and fork-specific port decision. |
| 364 | 2026-07-18 | `4e292c9` | chore: bump version to 3.0.5 | **Pending** | Pending functional review and fork-specific port decision. |
| 365 | 2026-07-18 | `6436d23` | Merge pull request #53 from fwerkor/chore/pr31-compat | **Pending** | Pending functional review and fork-specific port decision. |
| 366 | 2026-07-18 | `ce01734` | Merge pull request #31 from LeonardNJU/fix/version-consistency | **Pending** | Pending functional review and fork-specific port decision. |
| 367 | 2026-07-18 | `1a98ac4` | Merge pull request #54 from fwerkor/chore/version-3.0.5 | **Pending** | Pending functional review and fork-specific port decision. |
| 368 | 2026-07-18 | `a9db53f` | fix(ui): improve mobile WebUI interaction | **Pending** | Pending functional review and fork-specific port decision. |
| 369 | 2026-07-18 | `4384a6e` | fix(ui): harden touch input mode switching | **Pending** | Pending functional review and fork-specific port decision. |
| 370 | 2026-07-18 | `d155eac` | fix(ui): preserve soft keyboard across shortcut taps | **Pending** | Pending functional review and fork-specific port decision. |
| 371 | 2026-07-18 | `e30df0f` | fix(ui): guard first touch shortcut after mouse input | **Pending** | Pending functional review and fork-specific port decision. |
| 372 | 2026-07-18 | `b1cdbe2` | fix(ui): replace Ctrl+Q with Alt+Q | **Pending** | Pending functional review and fork-specific port decision. |
| 373 | 2026-07-18 | `c7c8919` | chore(ui): refresh embedded WebUI assets | **Pending** | Pending functional review and fork-specific port decision. |
| 374 | 2026-07-18 | `9fb2e89` | fix(ui): make Alt+Q exit reliable | **Pending** | Pending functional review and fork-specific port decision. |
| 375 | 2026-07-18 | `52d04d9` | fix(ui): confirm WebUI exits from the server | **Pending** | Pending functional review and fork-specific port decision. |
| 376 | 2026-07-18 | `6533324` | fix(ui): reconnect after abnormal TUI exits | **Pending** | Pending functional review and fork-specific port decision. |
| 377 | 2026-07-18 | `623918f` | test(ui): avoid double-clicking during smoke retries | **Pending** | Pending functional review and fork-specific port decision. |
| 378 | 2026-07-18 | `7e1e5c8` | Merge pull request #51 from fwerkor/fix/image-preview-layout | **Pending** | Pending functional review and fork-specific port decision. |
| 379 | 2026-07-18 | `924872d` | Merge pull request #50 from fwerkor/fix/webui-fluid-size | **Pending** | Pending functional review and fork-specific port decision. |
| 380 | 2026-07-18 | `7efbe6d` | fix(audit): address payload retention and scope reviews | **Partial** | Payload size, retention, portability, and redaction scope are hardened. External detail files and audit-detail authorization remain deferred until a fork-native audit query/UI surface exists. |
| 381 | 2026-07-18 | `f9b54bd` | fix(ui): preserve zero-valued extended ANSI colors | **Pending** | Pending functional review and fork-specific port decision. |
| 382 | 2026-07-18 | `59531e8` | Merge remote-tracking branch 'origin/main' into fix/mobile-webui-repaint | **Pending** | Pending functional review and fork-specific port decision. |
| 383 | 2026-07-18 | `56c2b14` | Merge remote-tracking branch 'origin/main' into fix/remove-webui-ctrlq | **Pending** | Pending functional review and fork-specific port decision. |
| 384 | 2026-07-18 | `5e02d8c` | Merge pull request #40 from fwerkor/fix/audit-full-payloads | **Partial** | Portable bounded backend payload retention is implemented; full external payload retrieval and Human UI expansion remain deferred. |
| 385 | 2026-07-18 | `2fec2b3` | Merge pull request #42 from fwerkor/fix/terminal-output-scrolling | **Pending** | Pending functional review and fork-specific port decision. |
| 386 | 2026-07-18 | `c6b2e21` | fix(audit): preserve nested failures when collapsing calls | **Implemented (equivalent behavior)** | Nested failure structures are retained directly in `tool_call_end.error`; no collapse step exists that could discard child causes. |
| 387 | 2026-07-18 | `c9347ea` | Merge remote-tracking branch 'origin/main' into fix/audit-call-aggregation | **Pending** | Pending functional review and fork-specific port decision. |
| 388 | 2026-07-18 | `6c4d7b5` | Merge remote-tracking branch 'origin/main' into fix/webui-fullscreen-escape | **Pending** | Pending functional review and fork-specific port decision. |
| 389 | 2026-07-18 | `2684f30` | Merge remote-tracking branch 'origin/main' into fix/webui-mouse-wheel | **Pending** | Pending functional review and fork-specific port decision. |
| 390 | 2026-07-18 | `3c0bb5f` | chore(ui): rebuild embedded assets with CI Bun version | **Pending** | Pending functional review and fork-specific port decision. |
| 391 | 2026-07-18 | `bc8cf52` | chore(ui): rebuild embedded assets with CI Bun version | **Pending** | Pending functional review and fork-specific port decision. |
| 392 | 2026-07-18 | `00f563f` | chore(ui): rebuild embedded assets with CI Bun version | **Pending** | Pending functional review and fork-specific port decision. |
| 393 | 2026-07-18 | `2e8952f` | chore(ui): rebuild embedded assets with CI Bun version | **Pending** | Pending functional review and fork-specific port decision. |
| 394 | 2026-07-18 | `a1d59c4` | fix(dashboard): handle missing telemetry and degraded sources | **Pending** | Pending functional review and fork-specific port decision. |
| 395 | 2026-07-18 | `7c52e0b` | fix(audit): retain semantic child event details | **Implemented (equivalent behavior)** | Semantic child events remain independent JSONL records rather than being absorbed into a UI aggregation model. |
| 396 | 2026-07-18 | `342d81a` | Merge pull request #41 from fwerkor/fix/webui-fullscreen-escape | **Pending** | Pending functional review and fork-specific port decision. |
| 397 | 2026-07-18 | `e5c9aab` | Merge remote-tracking branch 'origin/main' into fix/webui-mouse-wheel | **Pending** | Pending functional review and fork-specific port decision. |
| 398 | 2026-07-18 | `169c108` | Merge remote-tracking branch 'origin/fix/webui-mouse-wheel' into fix/remove-webui-ctrlq | **Pending** | Pending functional review and fork-specific port decision. |
| 399 | 2026-07-18 | `de7a74c` | Merge remote-tracking branch 'origin/fix/remove-webui-ctrlq' into fix/mobile-webui-repaint | **Pending** | Pending functional review and fork-specific port decision. |
| 400 | 2026-07-18 | `24c1a3e` | Merge remote-tracking branch 'origin/fix/mobile-webui-repaint' into fix/audit-call-aggregation | **Pending** | Pending functional review and fork-specific port decision. |
| 401 | 2026-07-18 | `eafe358` | Merge remote-tracking branch 'origin/fix/audit-call-aggregation' into feat/dashboard | **Pending** | Pending functional review and fork-specific port decision. |
| 402 | 2026-07-18 | `1dca0c0` | Hide redundant WebUI terminal scrollbar | **Pending** | Pending functional review and fork-specific port decision. |
| 403 | 2026-07-18 | `ed7136b` | Merge pull request #44 from fwerkor/fix/webui-mouse-wheel | **Pending** | Pending functional review and fork-specific port decision. |
| 404 | 2026-07-18 | `5035536` | Merge pull request #39 from fwerkor/fix/remove-webui-ctrlq | **Pending** | Pending functional review and fork-specific port decision. |
| 405 | 2026-07-18 | `e17e9d7` | Merge pull request #36 from fwerkor/fix/mobile-webui-repaint | **Pending** | Pending functional review and fork-specific port decision. |
| 406 | 2026-07-18 | `ab97555` | Merge pull request #49 from fwerkor/fix/audit-call-aggregation | **Split follow-up** | The merge completes upstream audit-call aggregation for its Human UI. The fork intentionally retains paired JSONL events until its own UI design is ported. |
| 407 | 2026-07-18 | `d80dae9` | Merge remote-tracking branch 'origin/main' into fix/webui-hide-scrollbar | **Pending** | Pending functional review and fork-specific port decision. |
| 408 | 2026-07-18 | `14053a1` | fix(ui): clear terminal commands after submit | **Pending** | Pending functional review and fork-specific port decision. |
| 409 | 2026-07-18 | `c753f9c` | Merge pull request #55 from fwerkor/fix/webui-hide-scrollbar | **Pending** | Pending functional review and fork-specific port decision. |
| 410 | 2026-07-18 | `71d2383` | Merge pull request #52 from fwerkor/feat/dashboard | **Pending** | Pending functional review and fork-specific port decision. |
| 411 | 2026-07-18 | `d9f006f` | chore: bump version to 3.0.6 | **Pending** | Pending functional review and fork-specific port decision. |
| 412 | 2026-07-18 | `e5410ae` | Merge pull request #56 from fwerkor/release/v3.0.6 | **Pending** | Pending functional review and fork-specific port decision. |
