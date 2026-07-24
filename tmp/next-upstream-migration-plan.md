# Next upstream migration plan

Status: Phases 1-8 complete; Phase 9 pending. Phase 8 closure CI is recorded; this record commit's exact-head CI remains to be verified.

Temporary source of truth: this file is intentionally tracked by Git while the
migration is in progress. Update its checkboxes and decisions in the same commits
that implement each phase. Delete it only after every exit criterion is complete
and the durable user/developer documentation contains the final architecture.

## Audited baseline

| Role | Ref | Commit |
|---|---|---|
| Fork branch | `feat/port-upstream-features-2026-07` | `9697a5b9727316a93acf838bf77ff4eada7455fe` |
| Fork baseline | `main` | `c40067a` |
| Upstream reference | `upstream/main` | `9f1484e880c01b64b320ce0105de6bee831821e7` |
| Shared historical fork point | merge base | `e1f2dc0aa43ebcc72b5b47470daac446d7d02c8e` |

The implementation should preserve fork-native sessions, jobs, security, remote
worker upgrades, Windows support, and UI architecture. Upstream code is a
behavioral reference, not a patch set to copy mechanically.

## Confirmed product decisions

These decisions are no longer pending:

1. Keep the dynamic Agent Bridge and installed Skills as product features.
2. Add managed static secrets and OAuth for bridged HTTP/SSE MCP servers.
   The primary interactive command will be `local-shell-mcp mcp auth <server>`.
3. Keep controller-authorized automatic remote-worker runtime upgrades.
4. Keep raw authenticated local and remote browser terminals.
5. Keep all three UI clients: browser-native Human UI, native OpenTUI, and the
   browser OpenTUI Console.
6. Keep bundled tmux binaries in supported frozen Linux release archives.
7. Port real browser E2E, worker user-service management, embedded OpenTUI
   platform wheels, public MCP `audit_tail`, HTTP large-file transfer, and full
   recovery of retained oversized audit payloads.
8. Integrate structured environment information into `session_start` and
   `session_change_cwd`; do not add a standalone `environment_info` tool.
9. Remove the stale-tool diagnostic/tombstone compatibility layer completely.
   Unknown or removed tool names must receive the normal MCP unknown-tool error.
   Do not add aliases or hidden migration fallbacks.

## Cross-cutting rules

- Every workspace- or machine-scoped MCP capability uses an explicit
  `session_id`. Do not restore optional `machine` arguments across ordinary
  tools.
- New remote behavior must work through the existing worker identity, capability,
  and automatic-upgrade model. Protocol capability fallback is allowed; removed
  tool-name compatibility is not.
- Secrets, OAuth tokens, worker credentials, transfer authorization values, and
  approval data must never appear in argv, manifest plaintext, URLs, logs,
  generated docs, public status responses, or unredacted audit records.
- Audit redaction runs before any value is externalized to payload storage.
- New large-body routes must stream and enforce their own limits; they must not
  cause the shared request-limit middleware to buffer an entire transfer.
- Local and remote outputs use the same typed result models where the semantics
  are the same.
- Each phase should be independently reviewable and leave the full repository
  testable. Prefer one feature family per commit series rather than one final
  monolithic change.
- Update `upstream-commit-review.md`, `fork-upstream-differences.md`, generated
  references, security docs, and coverage baselines in the phase that changes
  their truth.
- No phase is complete until pre-commit, Pyright, the relevant focused tests, and
  the applicable cross-platform CI jobs pass.

## Delivery order

The sequence below is dependency-driven. In particular, browser E2E becomes the
UI regression harness, Agent Bridge authentication is established before it is
reported by session orientation, and the recoverable audit store is implemented
before `audit_tail` exposes full details.

### Phase 0 — Track and maintain this plan

- [x] Record approved scope and architecture in this tracked temporary file.
- [ ] Update phase status and any reviewed contract changes as implementation
      proceeds.
- [ ] Keep the branch synchronized with `upstream/main` and append newly reviewed
      upstream commits before claiming final parity.

Exit criterion: this file is committed and is the only temporary migration plan.

### Phase 1 — Remove stale-tool diagnostics and compatibility tombstones

Status: complete (2026-07-23); implementation commit `6212b776c3f86cbdd21cb67d4cac00fe11f0f67f`, checkpoint commit `3af71668eb20afcaef6472db20c85897a7a65cda`.

Actual baseline: branch HEAD and
`origin/feat/port-upstream-features-2026-07` both point to `2710cdb`; fetched
`upstream/main` remains `f72164a`, so no post-baseline upstream commits require
review before this phase. Code audit confirms the compatibility layer is
implemented only by `deprecated_tools.py` plus `DeprecatedToolFastMCP` and its
documentation/tests. `relaxed_client_tool_hints` has no runtime consumer: it is
only a no-op settings/surface entry with generated-reference and test coverage,
so Phase 1 removes it rather than renaming it. Existing exact tool-surface tests
remain authoritative; the stdio E2E test will cover the SDK protocol error.

Implementation:

- Delete `src/local_shell_mcp/deprecated_tools.py`.
- Replace `DeprecatedToolFastMCP` with the SDK `FastMCP` in
  `src/local_shell_mcp/server/mcp/app.py`.
- Delete `tests/test_deprecated_tools.py` and remove the module from the coverage
  baseline.
- Remove all stale-tool, replacement-name, refresh/re-add, and tombstone wording
  from server instructions, generated references, permanent docs, maintenance
  reports, and tests.
- Remove `relaxed_client_tool_hints` if its only remaining purpose is obsolete
  compatibility behavior; otherwise rename/document its actual semantics rather
  than retaining a deprecated flag.
- Do not retain a name map, compatibility subclass, hidden alias, or custom
  unknown-tool response anywhere else.

Public contract:

- Current tools remain unchanged.
- Removed names are absent from `tools/list` and fail through the standard MCP
  unknown-tool path.
- `environment_info` is not restored as a tool or tombstone; structured
  environment data arrives later through `session_start`.

Tests:

- Exact public tool-surface tests.
- A protocol-level assertion that an unknown tool receives the SDK-standard
  error and no replacement guidance.
- Generated tool-reference and server-instruction checks.

Implementation result (2026-07-23): the custom module/subclass and its dedicated
tests were deleted; `build_mcp()` now constructs the SDK `FastMCP` directly.
The no-op `relaxed_client_tool_hints` field was removed from settings, the
configuration surface, examples, generated configuration reference, tests, and
permanent security documentation. The coverage baseline and maintenance reports
now reflect the removal. Current tool schemas and names were not changed, and
`environment_info` remains absent.

Validation: the original 18-test Phase 1 group passed. Five added regression
tests for the SDK SSE fallback, PowerShell/cmd environment assignment rendering,
empty output chunks, and shared stderr tail capacity also passed. The final full
Linux branch-coverage run passed with `773 passed, 1 skipped`, 83.70% total
coverage against the unchanged 82.60% baseline, 181
tracked modules, and zero new untracked coverage modules. The initially exposed
`server/mcp/app.py` and `ops/shell.py` module gaps were closed without weakening
production behavior or the coverage baseline.

Ruff format/check, Pyright, generated configuration/reference byte comparison,
`git diff --check`, strict MkDocs, and all three generated reference asset checks
passed. Repository search has zero matches for the Phase 1 implementation
identifiers. Secret scan findings are limited to pre-existing fake fixtures in
unchanged files. The staged repository-wide pre-commit suite passed every hook.
Phase implementation commit: `6212b776c3f86cbdd21cb67d4cac00fe11f0f67f`.

Exit criterion: repository search finds no `DeprecatedTool`, `DEPRECATED_TOOLS`,
`stale_tool_snapshot`, or compatibility-diagnostic implementation.

### Phase 2 — Add real Chromium browser E2E

Status: complete (started and completed 2026-07-23).

Actual baseline: branch HEAD and
`origin/feat/port-upstream-features-2026-07` both point to `3af7166`; fetched
`upstream/main` remains `f72164a`, so no post-baseline upstream commits require
review before this phase. The implementation will be based on an audit of the
fork's current OAuth, Human UI, terminal, remote-worker, and browser Console
architecture plus the upstream browser-test behavior; no public browser tools
will be restored.

Audit/design result: the fork already exposes stable browser element ids, a
native Web Crypto S256 PKCE client, scoped Human UI APIs, authenticated terminal
and OpenTUI WebSockets, generation guards for stale file/dashboard responses,
revision-guarded Todos, and real remote-worker process helpers. The upstream
`scripts/ui-smoke.py` is a large TUI-centric monolith with incompatible selectors,
so only its product behaviors are being ported. Phase 2 will use modular pytest
scenario helpers under `tests/browser/`, one small launcher, one real server and
worker fixture, Playwright tracing plus bounded logs, and a dedicated Ubuntu job.
The normal Linux/macOS/Windows pytest matrix will collect the browser module but
skip it unless the launcher enables `LOCAL_SHELL_MCP_BROWSER_E2E=1`; native
OpenTUI remains covered by the existing Bun matrix. Chromium revision pinning is
owned by the locked Playwright development dependency, not by a public runtime
dependency or a new MCP tool.

Implementation:

- Add Playwright as a development/CI dependency only; do not restore public
  browser automation tools in this phase.
- Add a fork-native browser harness under `tests/browser/` with a small launcher
  script under `scripts/`. Reuse test helpers rather than copying upstream's
  monolithic `scripts/ui-smoke.py` verbatim.
- Start a real loopback HTTP server with isolated workspace/state, complete OAuth
  authorization with S256 PKCE, and launch headless Chromium.
- Add a dedicated Ubuntu CI job that installs the pinned Chromium runtime. Keep
  ordinary route/API tests on Linux, macOS, and Windows.
- Upload Playwright trace, screenshot, browser console, server log, and worker log
  artifacts on failure.

Implementation result to date (2026-07-23): the modular harness and dedicated
Chromium job are implemented. The job explicitly installs `tmux`, builds the
browser OpenTUI runtime, installs the Chromium revision locked by Playwright, and
retains trace, screenshot/video, browser/page/request/WebSocket diagnostics, and
server/worker logs on failure. A complete local run passes all nine scenario
groups against a real OAuth server and worker. Real-browser audit exposed and the
implementation corrected four fork integration defects rather than weakening the
tests: HTTP mode now mounts the existing remote-worker routes when remote support
is enabled; HTTP `403` no longer clears a valid OAuth token; non-zero OpenTUI
process exits close abnormally so reconnect can run; and a valid empty PTY bridge
poll (`bytes=0`) is no longer rejected as malformed. The xterm Image Addon's
required inline Wasm decoder is allowed only through CSP `wasm-unsafe-eval`;
general `unsafe-eval` remains forbidden. These facts are reflected in permanent
Human UI, security, fork-difference, and upstream-review documentation.

Required scenarios:

1. unauthenticated `/ui` and API access, login redirect, authorization approval,
   callback, and connected state;
2. dashboard/version/capability rendering;
3. Files navigation, preview/edit/write, stale-response protection, copy/move/
   rename, and local/remote machine isolation;
4. Todos local/remote isolation;
5. Audit list/detail filtering and scope reauthorization;
6. local terminal create, input, output, resize, reconnect, stop, and scroll;
7. real remote-worker enrollment, machine switching, remote Files, and remote
   terminal input/output/resize;
8. browser OpenTUI Console start, authenticated WebSocket, resize, intentional
   stop, and abnormal-process reconnect behavior;
9. responsive desktop and narrow viewport layouts, keyboard focus, mouse/wheel,
   and no uncaught browser-console errors.

The native OpenTUI continues to use Bun/Node tests; browser E2E covers only the
browser-hosted clients.

Exit criterion: the browser job is required in CI and fails reproducibly on an
OAuth, Human UI, raw PTY, remote-machine, or browser Console regression.

Local validation result:

- Real Chromium launcher: `1 passed` in 20.72 seconds on the final clean run.
- Focused Human UI/remote/terminal/OpenTUI suite: `44 passed, 1 skipped`;
  the browser module remains intentionally skipped outside the dedicated launcher.
- Full branch-coverage suite: `777 passed, 2 skipped`; total branch coverage
  83.69% versus the 82.60% baseline; the 181-file module ratchet passed with no
  new untracked coverage modules and no baseline reduction.
- `ruff format --check`, `ruff check`, `pyright`, lockfile validation, generated
  configuration/tool/instruction checks, `git diff --check`, strict MkDocs build,
  and all three generated documentation reference-asset checks passed.
- Repository secret scan reported only existing simulated credentials/test
  fixtures in files untouched by this phase; no Phase 2 source, harness, workflow,
  documentation, or retained log artifact introduced a secret finding.

Implementation commit: `1b8fed50309a67bc672d714e2f2ec062a6a9050b`
(`test(ui): add real Chromium browser E2E`) and checkpoint commit
`68b1278c917da9ee9b925d3307e60c766175bd3f` were pushed. Docs and every CI job
except Ubuntu branch coverage passed, including the new Chromium Human UI E2E,
Windows/macOS suites, OpenTUI matrix, Windows ConPTY, package smoke, VS Code,
Docker, pyright, and pre-commit. Ubuntu failed only in the existing real tmux
bridge test because the test wrote input before the newly attached tmux client
had emitted its shell prompt; the input was echoed during attach initialization
but did not reach bash. This is a timing-sensitive test setup defect, not a bridge
or browser runtime failure. The first remediation attempt waited for tmux client
registration and sent bounded xterm-like capability, color, and size responses.
That attempt passed 30 consecutive local runs, the 30-test terminal suite, the
full `777 passed, 2 skipped` coverage suite at 83.69%, final Chromium, static,
generated-reference, and documentation gates. Remediation commit
`ca61f77ebb22fc7612fc5f086c77bad4a926134b` was pushed, and every remote job
except Ubuntu branch coverage passed again; the second Ubuntu failure proved that
attempt was still not a deterministic barrier. The second Ubuntu failure
refined the race: client registration and synthetic xterm responses were both
unsuitable test barriers because a pending response could be concatenated with the application command. Code audit also confirmed inherited
`PS1` is not a reliable interactive Bash contract. The final test now starts Bash
with a temporary `--rcfile` that clears `PROMPT_COMMAND` and emits the exact plain
`BRIDGE_READY> ` prompt. It waits for that prompt through the raw bridge before
sending application input, with no synthetic terminal responses, client polling,
production change, or timing sleep. A standalone equivalent and the repository
test each passed 60 consecutive iterations; the complete terminal bridge/Human UI
terminal suite passed 30 tests. Final local validation then passed: `777 passed,
2 skipped`, 83.69% total branch coverage with the unchanged 181-file ratchet;
real Chromium `1 passed` in 28.63 seconds; ruff format/check, pyright, lockfile,
generated configuration/tool/instruction, `git diff --check`, strict MkDocs, and
all three reference-asset checks passed. Secret scanning still reports only the
existing simulated credentials/fixtures in files untouched by this remediation.
Final remediation commit `083d3e8a5e02905a3346212839060596751c3c62`
(`test(terminal): wait for tmux shell prompt`) was pushed. GitHub Actions run
`29983021351` completed successfully: Ubuntu branch coverage, real Chromium,
Windows/macOS pytest, Windows ConPTY, all OpenTUI jobs, pyright, pre-commit,
package smoke, bundled tmux, VS Code, Docker/Compose, and release-matrix jobs all
passed. Phase 2 has no unresolved design, implementation, test, or CI issue; Phase
3 is the next pending phase.

### Phase 3 — Add Agent Bridge secret storage and OAuth client authentication

Status: complete (started and completed 2026-07-23).

Actual baseline: branch HEAD and
`origin/feat/port-upstream-features-2026-07` both point to `553161d`; fetched
`upstream/main` remains `f72164a`, so no new upstream commit requires review
before this phase.

Initial audit: the existing manifest supports only literal `env` and `headers`;
there is no private Agent Bridge credential store or per-server auth metadata.
The installed MCP SDK is 1.28.0 and already provides `OAuthClientProvider` plus
the asynchronous `TokenStorage` protocol, including discovery, PKCE/state,
dynamic registration, refresh, and HTTPX integration. The implementation will
reuse those primary SDK interfaces. Existing cross-platform private file locks
and atomic owner-only writes in `utils/private_files.py` will back a dedicated
`state_dir/agent_auth` store. Dynamic Agent Bridge tool reload currently
fingerprints only manifest/Skill files, so auth-store changes must join that
fingerprint to make successful secret/auth changes visible without restart.

Configuration contract:

- Extend the existing Agent Bridge manifest schema rather than adding a second
  MCP configuration file.
- Keep literal `headers` and `env` for non-secret static values.
- Add structured secret references for HTTP headers and stdio environment
  variables. Secret values live only in a private credential store and are
  resolved at connection time.
- Add per-server authentication metadata with modes `none`, `secret`, and
  `oauth`. OAuth is valid only for HTTP/SSE transports.
- Status and registry payloads report only auth mode, authorization state,
  expiry/status metadata, and redacted key names.

Credential storage:

- Add a dedicated private state subtree, separate from the read-oriented Agent
  Bridge manifest, for example `state_dir/agent_auth/`.
- Use owner-only directories/files, cross-process locking, atomic replace,
  bounded JSON, schema versions, and corruption errors rather than silent reset.
- Store OAuth tokens and dynamic client information through an implementation of
  the MCP SDK `TokenStorage` protocol.
- Do not put secrets or tokens in environment variables unless they are being
  injected into the lifetime of an explicitly configured stdio child process.

CLI contract:

```text
local-shell-mcp mcp auth <server> [--no-open]
local-shell-mcp mcp auth <server> --status
local-shell-mcp mcp auth <server> --logout
local-shell-mcp mcp secret set <server> <name> --stdin
local-shell-mcp mcp secret list <server>
local-shell-mcp mcp secret delete <server> <name>
```

- `mcp auth` uses the MCP SDK `OAuthClientProvider`, a loopback callback on
  `127.0.0.1` with an ephemeral port, PKCE/state validation, dynamic client
  registration when required, token refresh, and an optional printed URL when a
  browser cannot be opened.
- Secret values are read only from bounded UTF-8 stdin, never from positional or
  option argv. Interactive terminal stdin is refused.
- Successful auth immediately probes `tools/list`, persists the resulting state,
  and refreshes the Agent Bridge registry without restarting the server.
- Logout deletes local token/client state and attempts remote revocation only
  when supported; failure to revoke remotely must be reported explicitly.

Runtime integration:

- Inject the SDK OAuth auth provider into the existing `httpx.AsyncClient` used
  by `streamable_http_client`/SSE.
- Resolve secret references immediately before opening the configured transport.
- Preserve current timeout, redaction, dynamic-tool hot reload, and short-lived
  client-session behavior.

Implementation result:

- Manifest version 1 now accepts literal values or `{"secret": "name"}` references
  and validates mutually coherent `none`, `secret`, and `oauth` modes. Secret
  references are allowed only in `secret` mode; OAuth is limited to HTTP/SSE.
- `state_dir/agent_auth/credentials.json` is a versioned 1 MiB-bounded private
  store with 64 KiB per-secret limits, cross-process locking, atomic owner-only
  writes, explicit corruption/schema errors, concurrent mutation support, and no
  silent reset. It persists static secrets, SDK tokens/client information,
  absolute expiry, and discovered public authorization-server metadata.
- The MCP SDK provider is reused for discovery, DCR, PKCE/state, token exchange,
  HTTP auth, and refresh. Persisted expiry/metadata make refresh work after process
  restart; failed refresh removes stale tokens while preserving client/metadata.
  Normal server operation is fail-fast and noninteractive when reauthorization is
  required.
- CLI commands implement secret set/list/delete and OAuth authorize/status/logout.
  Authorization uses a bounded one-shot random `127.0.0.1` callback and verifies
  success with `tools/list`; logout discovers and attempts token revocation before
  clearing local credentials and reports the remote result.
- Stdio/HTTP/SSE transports resolve credentials only at connection time. Public
  status, dynamic descriptions, errors, and tool payloads use resolved redaction
  maps but expose no secret values or reference names. Credential file changes are
  included in the dynamic registry fingerprint for no-restart reload.
- Permanent Agent Bridge, configuration, quickstart, security, and fork-difference
  documentation now describes the workflow and upstream-server trust boundary.

Tests:

- Private/atomic credential store, concurrent writers, corruption, permission,
  and redaction tests.
- Fake OAuth protected-resource/authorization-server integration covering
  discovery, registration, PKCE/state, callback, token refresh, logout, and
  denied/expired flows.
- Static secret injection tests proving values are absent from argv, status,
  logs, exceptions, audit, and generated schemas.
- Hot reload and dynamic tool invocation after auth without process restart.

Final local validation:

- The focused Agent Bridge/auth/CLI suite passes 121 tests. It covers private
  permissions and corruption, concurrent writers, size/schema bounds, all auth
  status modes, secret injection/redaction, CLI lifecycle/errors, loopback
  callback validation, SDK discovery/DCR/PKCE/state, restart refresh, failed
  refresh, revocation, noninteractive runtime, and existing bridge regressions.
- The full branch-coverage suite passes `830 passed, 2 skipped`; total branch
  coverage is 84.23% versus the unchanged 82.60% baseline. New modules are
  individually above the required 90% (`auth.py` 97.01%, `auth_store.py` 98.14%,
  `cli.py` 92.59%); `models.py` improves to 97.07%. The 181-file ratchet accepts
  the three high-coverage new modules with no existing baseline reduction.
- The real Chromium Human UI scenario passes in 20.47 seconds. Repository-wide
  ruff format/check, pyright, lockfile, generated configuration/tool/instruction,
  public-docstring, `git diff --check`, strict MkDocs, and all three generated
  reference-asset checks pass. The Phase 2 raw tmux integration test also passes
  80 consecutive stress iterations after its terminal-emulator handshake was
  made deterministic with a fresh-prompt input barrier.
- Secret scanning reports zero findings in every Phase 3 source and test file.
  Existing simulated fixtures elsewhere remain unchanged.

Repository-wide pre-commit passed. Implementation commit
`aa066e793cebdc5397857260574bb85b8f5e1481`
(`feat(agent): add private secrets and OAuth clients`) and checkpoint commit
`8e8850db1128525d8deb4b008dbad929f6d459b9` were pushed. Docs run
`29986940423` and CI run `29986940426` completed successfully; all Linux, macOS,
Windows, Chromium, coverage, ConPTY, OpenTUI, package, VS Code, Docker, bundled
tmux, pyright, pre-commit, and release-matrix jobs passed. Phase 3 has no
unresolved design, implementation, test, security, documentation, or CI issue;
Phase 4 is complete below; Phase 5 is the next pending phase.

Exit criterion: an HTTP MCP server requiring OAuth and a stdio/HTTP server
requiring a stored secret can both be configured and called without plaintext
credentials in the manifest.

### Phase 4 — Merge structured environment information into sessions

Status: complete (started and completed 2026-07-23).

Actual baseline: branch HEAD and `origin/feat/port-upstream-features-2026-07` both point to `509ccc4`; fetched `upstream/main` remains `f72164a`, so no new upstream commit requires review before this phase.

Initial audit: local sessions already compute Git/instruction orientation off the event loop, but remote `session_start` discards the worker's structured payload and rebuilds placeholders on the controller; `session_change_cwd` is synchronous and rejects remote sessions. Phase 4 will preserve worker-generated orientation/environment, add remote cwd changes through the existing worker session, and cache only the worker-returned canonical workdir on the controller. Tool/version probes will run concurrently with independent bounded subprocess timeouts and expose only normalized status/version/source fields.

Do not add `environment_info`. Extend the current `SessionStartOutput` with one
nested, typed `environment` object returned by both `session_start` and
`session_change_cwd`.

Planned environment groups:

- `runtime`: local-shell-mcp version, Python implementation/version, source/
  frozen runtime, OS, release, architecture, and process bitness;
- `workspace`: workspace root, canonical workdir, target, machine, and remote
  worker runtime identity/version;
- `tools`: allowlisted executable availability and bounded version probes for
  shell, Git, ripgrep, tmux, curl, Bun, Chromium/Playwright, and OpenTUI;
- `capabilities`: remote worker, raw PTY, ConPTY, browser UI, native OpenTUI,
  browser Console, Agent Bridge, OAuth-backed MCP clients, HTTP transfer, audit
  full-payload recovery, and worker service kind/status;
- `policy`: safe non-secret limits and modes relevant to tool choice, including
  authentication mode, full-control mode, shell/file/output limits, transfer
  limits, and remote enablement;
- existing Git orientation and nearby instruction-file discovery remain top-level
  or are nested consistently, but are not duplicated.

Implementation result:

- `SessionStartOutput` now contains one required typed `environment` object with
  fixed `runtime`, `workspace`, `tools`, `capabilities`, and `policy` groups.
  `session_start` and `session_change_cwd` return the same contract; no
  `environment_info` tool or alias was added.
- Tool probes are allowlisted, concurrent, independently limited to 1.5 seconds,
  output-bounded, version-token-only, and briefly cached. `available` is true only
  after a successful probe; missing, timeout, error, and unsupported states are
  normalized without executable paths, stdout/stderr, or exception text.
- Environment collection exposes only safe runtime/platform tokens, canonical
  session workspace/workdir, tool status/version/source categories, capability
  booleans/counts, and tool-selection limits. It excludes environment values,
  OAuth/admin secrets, Agent Bridge server names, denylists, state/config paths,
  worker digests, process arguments, and full executable paths. Collection errors
  degrade to normalized unavailable/error fields instead of failing sessions.
- OAuth capability changes are visible as configured/authorized upstream counts;
  the private auth store is not created when no enabled OAuth upstream exists.
- Remote `session_start` now validates and preserves the worker-generated Git,
  instruction, workspace, runtime, tool, capability, and policy payload instead
  of rebuilding controller-local placeholders. The controller rebinds only its
  public session id, target, machine, and lifecycle timestamps.
- `session_change_cwd` is now asynchronous and supports local and remote sessions.
  Remote changes execute through the paired worker session, cache only the
  worker-validated canonical workdir on the controller, and clear stale grounding
  snapshots. The source-only worker bundle includes the collector and internal
  cwd dispatch without adding public worker tools.
- Permanent workflow, remote-worker, security, quickstart, generated tool-schema,
  and fork-difference documentation describes the session-bound contract and
  disclosure boundary.

Implementation rules:

- Use Python/platform APIs and bounded executable probes, not an assembled shell
  command such as `uname; id; ...`.
- Cache machine-static probes briefly, while refreshing workdir-specific Git and
  instruction orientation on `session_change_cwd`.
- A remote worker's session-start response must carry the worker's own
  environment, Git orientation, instruction files, and workspace root. The
  controller must not replace them with local placeholders.
- Return only an allowlisted environment model; never return arbitrary process
  environment variables or credentials.

Tests:

- Typed schema and generated reference tests.
- Local source/frozen and Linux/macOS/Windows-normalized unit tests.
- Real remote-worker E2E proving remote metadata is produced on the worker.
- Capability changes after Agent Bridge auth, OpenTUI installation, and service
  installation are reflected correctly.

Final local validation:

- Focused session/environment/worker suites pass 97 tests across normalized
  probes, deterministic concurrency, brief cache behavior, failure fallback and
  redaction, OAuth authorization counts, local/remote cwd refresh, snapshot
  invalidation, source-only worker bootstrap, public schemas/docstrings, and the
  real controller/worker E2E.
- The real remote fixture passes in 7.48 seconds and proves worker-generated
  workspace root, canonical workdir, instruction files, runtime/tool/capability/
  policy data, private worker session routing, public session-id rebinding, remote
  cwd refresh, restoration, and later remote tools all work in one live flow.
- The full branch-coverage suite passes `846 passed, 2 skipped`; total branch
  coverage is 84.46% against the unchanged 82.60% baseline. The new internal
  `tool_session/environment.py` module is 93.63% and the expanded typed session
  schema is 100%; the 181-file ratchet passes with no existing baseline reduction.
- The real Chromium Human UI scenario passes in 31.39 seconds. Repository-wide
  ruff format/check, pyright, lockfile, generated configuration/tool/instruction,
  public tool-family alignment, strict MkDocs, all three generated reference
  assets, and `git diff --check` pass.
- Secret scanning reports zero findings in all 14 modified Phase 4 source and test
  files. Generated schemas confirm both session tools share exactly the same five
  environment groups and that no standalone `environment_info` tool exists.

Repository-wide pre-commit passed. Implementation commit
`5537c05cd226365c8e48d898c7c77c7705dbe297`
(`feat(session): add structured environment orientation`) and checkpoint commit
`5d495dbbb8ab8adbcb3c00e03ac217bfeabe1f8f` were pushed. Initial CI run
`29990231813` passed Ubuntu coverage, Chromium, pyright, pre-commit, package,
ConPTY, OpenTUI, VS Code, Docker, bundled tmux, and release checks, but its macOS
pytest job found a platform-specific test bug: the generic sentinel `private`
matched macOS's legitimate `/private/var/...` temporary path. The assertion now
uses the unique sentinel `probe-secret-fixture`; no production behavior changed.
Fix commit `4adce7c16d7f7825f317fd22bbcaf7e1ab9e8551` was pushed. Clean CI rerun
`29990557981` completed successfully, including Ubuntu coverage, Linux/macOS/
Windows pytest, Chromium, pyright, pre-commit, package, ConPTY, OpenTUI, VS Code,
Docker/Compose, bundled tmux, and release-matrix jobs. Docs run `29990231784`
also completed successfully. A later documentation-only closing checkpoint run
`29990885069` exposed a second pre-existing browser-test ordering race: terminal
polling observed the output marker before Playwright's WebSocket receive event was
recorded, and the helper asserted immediately. The helper now waits within the
same existing 15-second bound until both independent signals have arrived; a
regular unit regression reproduces the original ordering deterministically. No
production behavior changed. Stabilization commit
`fc3d313ffd0c4585b5b8e1974a8aae9b11b915c0`
(`test(browser): wait for terminal websocket event`) was pushed. Because GitHub
did not create a push check for that head, the complete workflow was explicitly
dispatched against the same branch head. Final CI run `29991510147` completed
successfully with all 19 jobs green: Ubuntu coverage, Linux/macOS/Windows pytest,
Chromium, pyright, pre-commit, package smoke, ConPTY, all OpenTUI and VS Code jobs,
Docker/Compose, both bundled-tmux architectures, and release-matrix checks. Phase
4 has no unresolved design, implementation, test, security, documentation, or CI
issue; Phase 5 is the next pending phase.

Exit criterion: clients can choose tools and understand local/remote runtime
capabilities from `session_start` alone, with no standalone environment tool.

### Phase 5 — Add recoverable oversized audit payloads and public `audit_tail`

Status: complete (started and completed 2026-07-23).

Actual baseline: branch HEAD and `origin/feat/port-upstream-features-2026-07`
both point to `2ba7f7b`; fetched `upstream/main` remains `f72164a`, so no new
upstream commit requires review before this phase. Phase 4 branch-head CI run
`29992872968` is complete/success.

Implementation result:

- Audit values are redacted/normalized first. The complete sanitized value keeps
  strings up to `max_audit_payload_bytes`, while JSONL previews retain the
  existing smaller display bounds. Large accepted values become canonical,
  deterministic-gzip, SHA-256-addressed objects under the private audit payload
  directory; small values remain inline and over-limit values become explicit
  omission records.
- References contain version, digest, canonical JSON byte count, creation time,
  and bounded preview. Full reads use no-follow regular-file opens and validate
  retention, compressed/read/decompression bounds, canonical byte count, digest,
  UTF-8, and JSON before returning data. Missing, corrupt, and expired objects
  remain explicit unresolved references rather than raw exceptions.
- Payload creation, JSONL append, lifecycle-pair retention, combined payload
  quota accounting, atomic JSONL rewrite, and payload pruning share the existing
  cross-process audit transaction. Repeated content repairs/replaces corrupt or
  symlinked objects atomically and does not follow the link target.
- Five bounded settings and generated config examples are implemented. Setting
  validation enforces inline <= per-value <= store quota; setting retention to
  zero disables recovery while leaving bounded references/omission behavior.
- Public `audit_tail` is a read-only, typed, explicit-session tool. Local reads
  reuse `query_audit`/`get_audit_entry`; remote reads use the paired worker
  session and existing internal audit RPCs. Full payload resolution is permitted
  only in stable `entry_id` detail mode.
- Dedicated `audit:read` and `audit:full` scopes are part of the supported OAuth
  set. The public tool requires `audit:read` and conditionally enforces
  `audit:full`; Human UI list/detail uses the same scopes while preserving the
  existing operation-sensitive write/execute/share/Git/remote checks.
- MCP/REST lifecycle wrappers bind the exact current call id. Local `audit_tail`
  excludes only its own in-progress lifecycle, so older audit queries remain
  visible and no broad event-family suppression is required.
- The source-only worker bundle includes the payload module; remote query/detail
  handlers preserve preview/full behavior without adding public worker tools.

Final local validation:

- The complete focused audit/config/UI/worker/remote/public-surface suite passes
  133 tests, including source-only worker bootstrap and the real controller/
  worker E2E. Direct failure-injection coverage validates malformed references,
  invalid roots/objects, open races, byte-count/digest/JSON/UTF-8 mismatches,
  bounded gzip bombs, recursive lists, quota pruning, and GC error paths.
- The full branch-coverage suite passes `876 passed, 2 skipped`; total branch
  coverage is 84.82% against the unchanged 82.60% baseline. The new
  `audit_payloads.py` module is 98.12%; the new operation, input schema, result
  schema, and registry modules are 100%. The ratchet passes across 181 tracked
  files and all nine new modules without reducing any existing baseline.
- Real Chromium passes with an approximately 24 KiB write payload that is actually
  externalized; the Audit detail recovers the full sanitized `payload-e2e-`
  content, then scope downgrade/restore still proves `audit:read`, `audit:full`,
  and operation-sensitive authorization behavior.
- Repository-wide ruff format/check, pyright, lockfile, generated config/tool/
  instruction checks, strict MkDocs, all three reference assets, and
  `git diff --check` pass. Secret scanning reports zero findings in all 28
  modified Phase 5 source and test files.

Repository-wide pre-commit passed. Implementation commit
`4bc64c527908758a48de2c4695cdda284a0dc2ee`
(`feat(audit): add recoverable payloads and audit tail`) and checkpoint commit
`0c5dfd11cccf553b3b18073744cae6a44813ffe6` were pushed. Docs run
`29998811896` completed successfully. Initial CI run `29998811993` passed
Chromium, macOS, pre-commit, pyright, package, ConPTY, OpenTUI, VS Code, Docker,
bundled tmux, and release checks, but Ubuntu exposed a real startup boundary in
the periodic payload sweep: when process uptime was below 60 seconds, a missing
last-sweep timestamp was treated as zero and the first orphan cleanup was delayed.
The implementation now treats an absent timestamp as immediately due; the
regression fixes monotonic time at one second so it cannot depend on host uptime.
The same run's Windows pytest exposed a separate shared-lock contention issue:
`msvcrt.LK_LOCK` exhausted its internal retry and returned `EDEADLK` under four
spawned writers. The Windows private-file helper now uses explicit nonblocking
lock attempts and retries only contention errno values, matching POSIX blocking
semantics while propagating unrelated I/O failures immediately. Deterministic
unit tests cover both paths. Clean CI run `29999693146` confirmed the deadlock
retry but exposed a preceding Windows race: competing processes could both see an
empty lock file and fail while flushing the sentinel byte before locking. Lock
files are now initialized or repaired before opening, using exclusive creation
and contention retries; `_lock_handle` only locks an already initialized byte.
The same run showed the payload spawn test's fixed 20-second per-process join was
too small under Ubuntu coverage without any child traceback. Both cross-process
tests now use one shared 90-second deadline and always terminate/reap stragglers
before failing. Final remediation commit
`9e05caa9ee8c01f0426cadadddb4f5145f6c3517`
(`fix(audit): initialize locks before contention`) passed clean branch-head CI
run `30003144133`: Ubuntu coverage, Windows/macOS pytest, Chromium oversized
payload recovery, pre-commit, pyright, package smoke, ConPTY, OpenTUI, VS Code,
Docker, bundled tmux, and the release matrix all completed successfully. The
final local suite is `876 passed, 2 skipped` at 84.82% branch coverage.

Phase 5 exit criteria are complete. Phase 6 is next; do not begin it without a
new user instruction.

#### Phase 5A — Recoverable payload store

Storage contract:

- Sanitize/redact a value first. Only the sanitized representation may be
  externalized.
- Keep small sanitized values inline. Store larger accepted values as
  deterministic gzip-compressed JSON objects addressed by SHA-256 under a
  private audit payload directory.
- Inline references contain a schema version, digest, original encoded byte
  count, and bounded preview.
- Verify digest and decompression bounds on every full read.
- Use no-follow/private file creation, atomic replace, owner-only permissions,
  and the same cross-process audit transaction boundary as JSONL retention.
- Retention accounts for JSONL plus referenced payload bytes, preserves paired
  tool lifecycle units, and garbage-collects unreferenced/corrupt/expired
  payloads after a grace period.

Settings to add with validated bounds:

- `audit_payloads_enabled` (default `true`);
- `audit_inline_value_bytes` (default 16 KiB);
- `max_audit_payload_bytes` (default 64 MiB per sanitized value);
- `max_audit_payload_store_bytes` (default 256 MiB total payload storage);
- `audit_payload_retention_s` (default seven days, also bounded by references and
  total quota).

“Full recovery” means byte-for-byte JSON recovery of the sanitized value while
its payload remains within these configured retention limits. Values above the
per-value limit remain explicit bounded omission records rather than causing an
unbounded write.

#### Phase 5B — Session-bound MCP `audit_tail`

Public tool contract:

```text
audit_tail(
  session_id,
  limit=100,
  event=None,
  operation=None,
  audit_session=None,
  search=None,
  start_ts=None,
  end_ts=None,
  sort="desc",
  entry_id=None,
  include_full_payloads=False,
)
```

- Reuse `query_audit` and `get_audit_entry`; do not copy upstream's raw backwards
  JSONL reader.
- Route local and remote sessions through the existing session/worker dispatch.
- Default responses expose coalesced bounded previews. `entry_id` selects one
  detail record. `include_full_payloads=true` resolves retained payload objects.
- Introduce dedicated OAuth scopes `audit:read` and `audit:full`; full payloads
  require both. Human UI detail access must use the same policy.
- Prevent recursive/noisy self-reporting by reading a stable snapshot and hiding
  the current `audit_tail` lifecycle record from its own result.
- Preserve all fork redaction and machine/session isolation.

Tests:

- Payload integrity, deterministic compression, concurrency, crash cleanup,
  corruption, decompression bombs, quota/expiry/pruning, lifecycle pairing, and
  secret-redaction-before-storage.
- Local/remote `audit_tail`, filters, stable ordering, detail, scope denial, full
  recovery, missing/corrupt payload behavior, and self-call exclusion.
- Browser E2E verifies preview/detail/full-payload authorization paths.

Exit criterion: an authorized client can recover a retained oversized sanitized
input/output locally or remotely, while an ordinary audit reader receives only
bounded previews.

### Phase 6 — Add remote-worker user-service management

Status: complete (started and completed 2026-07-23).

Actual baseline: branch HEAD and
`origin/feat/port-upstream-features-2026-07` both point to `be689fb`; fetched
`upstream/main` remains `f72164a`, so no new upstream commit requires review.
Phase 5 closure CI run `30003551128` completed successfully.

Implementation result:

- The old flat `worker --server ...` parser and reserved `--persist` flag are
  removed. The shared CLI and source-only entrypoint now use explicit
  `enroll`, `connect`, `run`, service lifecycle, logs, and update subcommands.
- Enrollment/resume is factored from the poll loop. `enroll` stores the existing
  private identity and exits, `connect` enters the foreground loop, and `run`
  requires the complete stored server/name/access/workdir identity. Invite stdin
  is bounded UTF-8, rejects TTY input, and is never printed.
- A stable private launcher under the worker state directory prefers the verified
  installed runtime and invokes only `worker run`. Generated systemd units and
  launchd plists contain no invite, access token, server URL, or other identity
  credential.
- Linux systemd-user and macOS launchd managers implement typed JSON status,
  idempotent install/uninstall/start/stop/restart, manager-unavailable errors,
  bounded logs, private launchd output, and interrupt-safe follow mode. Windows
  status is explicitly unsupported and no detached-process emulation is added.
- Manual `worker update` reuses the existing same-origin, digest-qualified,
  bounded, rollback-capable runtime installer. It supports `--force` and restarts
  the user service only when a new runtime was installed and the service was
  running before the update.
- Controller-directed reexec is credential-free and uses only `worker run` plus
  persisted identity. The existing inherited single-instance lock remains in
  place; the worker lock now reuses hardened pre-lock file initialization so
  managed restart/upgrade handoff cannot race on an empty lock file.
- The join script invokes the new `connect` subcommand and no longer advertises
  or passes `--persist`.

Final local validation:

- The complete repository suite passes `917 passed, 2 skipped`; total branch
  coverage is 85.23% against the unchanged 82.60% baseline. The new
  `remote_worker/cli.py` and `remote_worker/service.py` modules are 98.86% and
  96.49%; existing `lifecycle.py` and `runtime.py` remain above their stored
  baselines at 80.83% and 83.08%. The ratchet passes across 181 tracked files and
  11 new files.
- The focused worker/service/lifecycle/updater/CLI/remote/environment/public-
  surface group passes, including the real controller/worker E2E,
  dependency-light source-only CLI, safe native systemd-user status probe, and
  strict no-new-MCP-tool checks. Direct tests cover systemd/launchd generation
  and quoting, private permissions, credential exclusion, launcher change
  reloads, lifecycle idempotence, status/PID/error parsing, bounded logs and
  same-size rotation, unavailable managers, Windows unsupported behavior,
  invite stdin, enroll-only/stored-run behavior, verified force update,
  POSIX/Windows reexec, and managed-service PID failure fallback.
- Real Chromium passes after its worker harness was migrated to the explicit
  `connect` subcommand. Repository-wide ruff format/check, pyright, lockfile,
  generated config/tool/instruction checks, strict MkDocs, all three reference
  assets, and `git diff --check` pass.
- Secret scanning reports zero findings across every changed Phase 6 source and
  test file. The worker CLI/service/runtime source contains no literal bearer
  header, `access_token=` assignment, or `invite=` credential serialization.

Repository-wide pre-commit passed. Implementation commit
`8a80d024a0fc78aab4c265365dc0c135cce560d5`
(`feat(worker): add user service management`) and checkpoint commit
`f4f27c08a2a5c366a448a0770aa5d4790c5e1195` were pushed. Docs run
`30013103450` completed successfully. Initial CI run `30013103398` passed Ubuntu
coverage, macOS, Chromium, pre-commit, pyright, package, ConPTY, OpenTUI, VS Code,
Docker, bundled tmux, and release checks, but Windows exposed two portability
issues: a test compared an escaped systemd value to its raw Windows path, and
coarse filesystem timestamps could hide a same-size launchd-log rewrite. The
assertion now checks the generated quoted value, while log follow also compares a
bounded BLAKE2 tail signature so same-size rewrites are detected even when inode,
size, and mtime are unchanged. Remediation commit
`31bc336dc53fdc7a48f93c8824ec49c8a1667c13`
(`fix(worker): detect coarse log rewrites`) passes the post-fix local suite at
`917 passed, 2 skipped` and 85.23% branch coverage; `service.py` remains 96.49%
and the unchanged-baseline ratchet passes. Clean branch-head CI run
`30014177330` completed successfully with all 19 jobs green, including Ubuntu
coverage, Windows/macOS pytest, Chromium, pre-commit, pyright, package smoke,
ConPTY, OpenTUI, VS Code, Docker, bundled tmux, and the release matrix.

Phase 6 exit criteria are complete. Phase 7 is next; do not begin it without a
new user instruction.

CLI contract (intentional breaking cleanup; no hidden legacy parser):

```text
local-shell-mcp worker enroll --server URL (--invite VALUE | --invite-stdin) [--name NAME] [--workdir PATH]
local-shell-mcp worker connect --server URL (--invite VALUE | --invite-stdin) [--name NAME] [--workdir PATH]
local-shell-mcp worker run
local-shell-mcp worker install-service [--no-start]
local-shell-mcp worker uninstall-service
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker status
local-shell-mcp worker logs [--lines N] [--follow]
local-shell-mcp worker update [--force]
```

- `enroll` stores identity and exits; `connect` enrolls/resumes and runs in the
  foreground; `run` requires stored identity.
- Remove the reserved `--persist` flag and the old flat `worker --server ...`
  parser form rather than keeping aliases.
- Implement Linux `systemd --user` and macOS launchd first. Windows service
  installation remains an explicit unsupported result until a separate safe
  design is approved; do not emulate it with an untracked detached process.
- Units/plists invoke a stable launcher plus `worker run`, contain no invite,
  bearer token, or server credential, and use the existing private identity file.
- Install/uninstall/start/stop/restart are idempotent and return typed JSON status.
- `logs` uses `journalctl --user` for systemd and the managed private log for
  launchd, with bounded non-follow output and interrupt-safe follow mode.
- Integrate existing single-instance lock and cross-reexec handoff. A managed
  worker waits for an upgrade/restart handoff; a competing manual worker fails.
- `update` uses the existing digest/same-origin/rollback runtime updater and
  restarts the service only when it was running.

Tests:

- Unit/plist generation, quoting, private state, no credentials, idempotence,
  unavailable manager, command failures, status/log parsing, install/start/stop/
  restart/uninstall, and update-restart behavior.
- Existing POSIX and Windows worker lock/reexec tests remain required.
- Linux service smoke in a controlled user-systemd environment when CI supports
  it; launchd behavior is covered by command/plist tests plus macOS CI-safe
  probes.

Exit criterion: an enrolled Linux/macOS worker survives terminal exit and reboot
through an installed user service, and all lifecycle commands report truthful
state without widening the MCP tool surface.

### Phase 7 — Publish platform wheels with embedded OpenTUI

Status: complete (started 2026-07-23; completed 2026-07-24).

Actual baseline: branch HEAD and
`origin/feat/port-upstream-features-2026-07` both point to
`c5b7d27ed07f7161b43f18cca84ab2a1cd5138b7`; divergence is `0/0`, the worktree
was clean, and fetched `upstream/main` remains
`f72164a3d1883f83e22599c7e22e8e07fa6c77a8`. No newer upstream commit changes
the Phase 7 audit.

Implementation decision:

- Preserve `uv_build` and add a repository-owned build/verification command.
  It will compile with the repository-pinned Bun version into an isolated
  temporary directory, create deterministic gzip bytes in Python, stage exactly
  one bounded payload, build the ordinary wheel, rewrite `WHEEL` plus `RECORD`,
  and reject any filename, metadata, executable-magic, digest, size, or cleanup
  mismatch.
- Use explicit truthful tags: `linux_x86_64`, `linux_aarch64`,
  `macosx_10_15_x86_64`, `macosx_11_0_arm64`, and `win_amd64`. Support
  `win_arm64` validation only for a future native arm64 runner; do not publish it
  from x64 Windows. Linux wheels will not claim manylinux compatibility in this
  phase.
- Keep the universal wheel and sdist payload-free. Extend CI and release jobs to
  build native payloads on matching runners, inspect all artifacts, and install
  each platform wheel in an isolated environment with no Bun or sidecar before
  invoking the embedded executable.
- Reuse the existing fork-native `materialize_embedded_tui`; it already provides
  bounded streaming decompression, private versioned state, atomic replacement,
  fsync, executable permissions, and Windows/concurrent replacement handling.
  Add tests only where Phase 7 exposes a packaging or installed-wheel gap.

Rejected upstream design:

- Do not replace `uv_build` with Hatchling or use an environment-triggered build
  hook that infers the wheel tag. The tag and target runner must be explicit and
  independently verified.
- Do not place a native payload in the universal wheel, advertise an unaudited
  manylinux tag, cross-tag Windows x64 output as arm64, add an MCP tool, or alter
  controller/worker authorization or source-only remote-worker packaging.

Focused implementation checkpoint (2026-07-23):

- Added the typed `local_shell_mcp.platform_wheel` builder/inspector, thin build
  and installed-wheel smoke scripts, build-only `packaging`/`wheel` dependencies,
  five-runner CI/release matrices, atomic artifact download, and permanent
  packaging documentation. The public MCP registry is unchanged.
- Focused static checks passed. `57` builder tests cover all approved tags plus
  validation-only `win_arm64`, native host/magic checks, deterministic gzip and
  byte-reproducible ZIP/`RECORD` metadata, bounds, symlinks, external lock
  timeout/private permissions, subprocess failure, payload digests, corrupt
  archives, sdist exclusions, cleanup, and orchestration. The new production
  module has `91.64%` branch coverage.
- The broader focused set passed: `158 passed` across platform-wheel, TUI runtime,
  source-only worker bootstrap, real controller/worker E2E, CLI, and public tool
  surface tests.
- A real pinned-Bun Linux x86_64 build produced a verified non-pure
  `linux_x86_64` wheel with one 28 MiB gzip payload (about 95 MiB executable).
  Installing it into a clean virtual environment with Bun and sidecars absent
  materialized the runtime under the private versioned state directory and
  successfully executed `--version`.
- A real `uv build` produced one payload-free `py3-none-any` wheel and one
  source-only sdist; the sdist retained both repository scripts, excluded
  generated OpenTUI files, and rebuilt another verified payload-free wheel.
- The first real native build exposed one validator bug: `uv_build` emits an
  explicit `ui_runtime/` ZIP directory entry, which was incorrectly counted as
  a second payload. The inspector now counts only regular payload members and a
  regression fixture preserves the directory-entry case.
- Byte-level reproducibility testing then exposed that the original package-local
  build lock was included by `uv_build`; its PID changed the wheel and `RECORD`
  and leaked build-process metadata. The lock now lives in the system temporary
  directory under a repository-path hash, all ZIP members including `RECORD` use
  fixed metadata, and inspection rejects any packaged build lock. Two complete
  pinned-Bun builds separated in wall-clock time now have the identical wheel
  SHA-256 `71870fef03762579bc2a715d65b37ce67d4a80279ab042fcebf323cfc3eabf04`.

Full local verification checkpoint (2026-07-23):

- The required clean coverage workflow completed from an absolute-path detached
  script with `/tmp/phase7-full-coverage.log` and exit marker `0`: `974 passed,
  2 skipped`, aggregate branch coverage `85.39%` against the `82.60%` baseline,
  and the coverage ratchet accepted all `181` tracked plus `12` new files.
  `coverage.json`, `coverage.xml`, and `.coverage` were freshly generated by this
  run; `platform_wheel.py` remained at `91.64%` branch coverage.
- Repository-wide Ruff format/check, Pyright, `uv lock --check`, generated config
  and tool-reference checks, release-matrix validation, YAML parsing, and
  `git diff --check` passed. The generated MCP tool surface did not change.
  Final `pre-commit run --all-files --show-diff-on-failure` also passed all Ruff,
  generated-reference, VS Code, and terminal UI asset hooks.
- Strict MkDocs plus generated reference-asset validation passed. OpenTUI
  TypeScript checking and all `91` Bun tests passed. Real Chromium browser E2E
  passed (`1 passed`) and its artifacts were removed.
- Repository secret scans found no findings in every Phase 7 `src`/`tests` file
  or either new repository script. Manual review found no bearer/access/OAuth
  token, invite, admin PIN, credential-bearing URL/argv, unit, plist, or private
  absolute-path disclosure. No service lifecycle or authorization code changed.
- Main implementation commit: `d7e9a11` (`feat(packaging): publish embedded
  OpenTUI wheels`). It contains production code, tests, workflows, permanent
  documentation, lockfile changes, and release-matrix enforcement.

First remote CI checkpoints (2026-07-23):

- Pushed checkpoint `962583d4d33e16630caf7e2ee0728a32b2d5ef96` after confirming
  origin had not advanced. Exact-head Docs run `30023223610` succeeded.
- Exact-head CI run `30023221658` completed with two real Windows product
  failures while every other job succeeded. Platform-wheel job `89261019843`
  failed after Bun compilation while reading its 95 MiB payload on Python
  3.14.6 with `zlib.error: Error -3 while decompressing data: invalid distance
  too far back`. Ordinary Windows pytest job `89261019649` also failed because
  a dangling lock symlink was not rejected under Windows `os.open(O_EXCL)`
  semantics. Neither failure was runner infrastructure.
- Fix commit `d4aefd2` (`fix(packaging): stabilize Windows gzip payloads`) added
  fixed gzip metadata, explicit CRC32/ISIZE, bounded writes, an immediate full
  round-trip, and stable `zlib.error` wrapping. Local focused/full gates passed,
  but exact-head CI run `30024146148` proved that one large raw-DEFLATE stream
  still failed the Windows platform-wheel job `89264161560`; Windows pytest job
  `89264161553` also reproduced the dangling-symlink lock failure. The remaining
  22 jobs, including all Linux/macOS platform wheels and package/browser/release
  gates, succeeded.
- The final encoder uses standard concatenated gzip members: each at most 1 MiB,
  independently raw-deflated with a fixed header and its own CRC32/ISIZE trailer.
  This bounds every zlib stream while retaining deterministic compact output.
  The final lock path is outside the package tree and uses `lstat` before
  acquisition, `fstat`/`lstat` identity checks after `O_EXCL` creation, and the
  same checks before cleanup. Symlinks, non-regular files, path replacement, and
  cleanup of a lock not owned by the current builder are rejected. Final product
  fix commit: `65102b6` (`fix(packaging): harden Windows wheel builds`).
- Exact-head CI run `30025519243` on checkpoint `bcabfb4` proved the lock fix:
  ordinary Windows pytest succeeded, as did the other 22 jobs, including Linux
  and macOS platform wheels, Chromium, ConPTY, OpenTUI, VS Code, package smoke,
  Docker, and release-matrix validation. The sole failure was Windows x86_64
  platform-wheel job `89268863096`, which reported `embedded OpenTUI payload is
  not valid gzip` after the encoder's immediate round-trip had already passed.
  Forcing the final member to `ZIP_STORED` was necessary but not sufficient.
- Exact-head CI run `30026649855` on checkpoint `df51a34` completed with all 23
  other jobs successful; Windows x86_64 platform-wheel job `89272693465` alone
  failed with the same gzip error before installation. The remaining failing
  read was inside `_wheel_members` while opening the temporary uv-built universal
  wheel: `uv_build` had already ZIP-DEFLATE compressed the staged `.gz`, so the
  Windows builder still traversed the nested zlib path before the final wheel
  could replace that member.
- Root-cause fix commit `720326a` (`fix(packaging): inject verified wheel
  payloads`) requires exactly one staged payload entry but deliberately does not
  read its bytes. `rewrite_platform_wheel` receives the already round-tripped
  in-memory payload, verifies its source SHA-256, and injects it directly as
  `ZIP_STORED`. A permanent regression builds a temporary wheel containing an
  intentionally invalid staged payload and proves that rewrite never reads it.
- Two complete pinned-Bun Linux builds are byte-identical with wheel SHA-256
  `872d1bd8d13f33a0f8e09b9bb9d0c537f766c58086c7f546a579f98b916bd253`,
  and the clean no-Bun/no-sidecar installation still executes successfully.
- Final focused validation passed: `68 passed` for builder/docstring contracts,
  `168 passed` for the broader Phase 7 regression set, and
  `platform_wheel.py` retained `91.60%` branch coverage. The required clean full
  workflow completed from an absolute-path detached script with durable exit
  marker `0`: `984 passed, 2 skipped`, aggregate branch coverage `85.43%`
  against the `82.60%` baseline, and the coverage ratchet accepted all `181`
  tracked plus `12` new files. Repository-wide Ruff, Pyright,
  lock/generated-contract, release-matrix, whitespace, secret-scan, and
  all-files pre-commit gates passed.
- Exact-head CI run `30027732274` for checkpoint
  `4e0e7c99434422137b5b366fe7ac296b804f3d27` completed successfully with all
  24 jobs green. This includes Ubuntu/macOS/Windows pytest, real Chromium,
  Windows ConPTY, pre-commit, Pyright, package smoke, all OpenTUI and VS Code
  jobs, Docker/Compose, both bundled-tmux architectures, release-matrix checks,
  and native wheels for Linux x86_64/aarch64, macOS x86_64/arm64, and Windows
  x86_64. Phase 7 has no unresolved design, implementation, test, security,
  documentation, packaging, or CI issue. Phase 8 is next and must not begin
  without a new user instruction.
- Closure commit `08bcf5479497a075eded9baaeecf8c14b8a8b029`
  (`docs: close phase 7 migration`) was pushed after confirming origin had not
  advanced. Exact-head closure CI run `30028329550` completed successfully with
  the same 24/24 jobs green, including all five native platform-wheel jobs.

Packaging architecture:

- Keep `uv_build`; do not switch the entire project to Hatchling merely to copy
  upstream's hook.
- Add a deterministic platform-wheel builder that:
  1. builds the existing OpenTUI executable with pinned Bun;
  2. gzip-compresses it as bounded deterministic 1 MiB concatenated members;
  3. stages it as `local_shell_mcp/ui_runtime/<executable>.gz`;
  4. builds the wheel with `uv build`;
  5. requires exactly one staged payload entry but never reads its bytes;
  6. rewrites/verifies the `WHEEL` metadata as non-pure and assigns the explicit
     platform tag;
  7. injects the verified in-memory `.gz` payload as `ZIP_STORED`; and
  8. removes all staging files even on failure.
- Add build-only `wheel`/packaging tooling; do not add it to runtime dependencies.
- Continue publishing one universal `py3-none-any` wheel without a payload as the
  fallback for unsupported platforms and server-only installations.
- Publish same-version platform wheels for Linux x86_64/aarch64, macOS x86_64/
  arm64, and Windows x86_64. Do not claim a manylinux compatibility tag until the
  Bun binary is built and audited in an appropriate manylinux environment;
  initially use truthful platform tags.
- Reuse the fork's bounded/private/concurrency-safe `materialize_embedded_tui`.
  Sidecar and Bun-source fallback remain supported, not as old-name
  compatibility, but as supported installation modes.

Release/CI gates:

- Inspect wheel contents, filename tag, `Root-Is-Purelib`, executable digest, and
  absence of payload in the universal wheel.
- Install each platform wheel in a clean environment with Bun absent and no
  sidecar on `PATH`; verify `local-shell-mcp tui` resolves the embedded runtime
  and the native executable reports the expected version.
- Test concurrent first materialization, Windows replace races, corrupt/empty/
  oversized gzip, private permissions, and version-isolated cache paths.
- Update release-matrix checks and publish all wheel artifacts atomically with
  the sdist/universal wheel.

Exit criterion: `pip install` chooses a matching platform wheel and launches the
native OpenTUI without Bun or a release archive, while unsupported platforms can
still install the universal server wheel.

### Phase 8 — Add internal HTTP streaming for large `session_copy` transfers

Status: complete (started and closed 2026-07-24). Main implementation commit: `b9e649e627e3b70e457fa9936a5e92faa231f472` (`feat(remote): stream large session copies`); cross-platform security fix: `3e0e75a65f9b34f88385825ebd917c1347250a9e` (`fix(remote): harden transfer file identity`).

Actual implementation baseline: branch HEAD and
`origin/feat/port-upstream-features-2026-07` both pointed to
`cefbfec8fe65fe4e468b0f7a528e6d81c7fccda9`; the worktree was clean and
divergence was `0/0` after fetching both remotes. The completed implementation
commit is `b9e649e627e3b70e457fa9936a5e92faa231f472`; before checkpoint/push the
branch is `1/0` ahead of origin with only this migration-plan update unstaged.
On 2026-07-24, `upstream/main` advanced from
`f72164a3d1883f83e22599c7e22e8e07fa6c77a8` to
`9f1484e880c01b64b320ce0105de6bee831821e7` via merge `9f1484e` and functional
commit `889a7a1ddd4f7933e761564f4ed4f8a4822896a9` (`fix(worker): set product user
agent for updates`). The commit only adds a versioned `User-Agent` to
`remote_worker_installer.py` downloads and one installer test; it has no file or
semantic overlap with the Phase 8 gateway, copy routing, worker HTTP client,
session/worker authorization, or service lifecycle. It is recorded for Phase 9
parity review and is not transplanted in Phase 8.

Initial upstream/fork audit:

- Upstream's transfer ticket is itself a bearer secret embedded in
  `/remote/transfer/{direction}/{token}`; transfer routes bypass ordinary auth,
  tickets live only in memory, downloads have no Range resume, and upload
  request chunks are accumulated in memory. Tickets are not bound to the
  registered worker identity or fork session ids. These choices are rejected.
- The fork already has session-bound path authorization, same-worker direct
  copy, source digest/stat checks, transactional destination writes, durable
  background jobs, persisted worker identities/capabilities, and a source-only
  worker bundle. Phase 8 will extend these primitives rather than replace them.
- The accepted fork-native design keeps `session_copy` as the only public API,
  adds private controller routes with a non-secret route id plus a separate
  Authorization capability, persists hashed capability/ticket/spool state,
  binds every grant to worker, direction, session, size, digest, cursor, expiry,
  and nonce, and reuses the existing destination transaction for atomic commit.
- Cross-worker copies stage through a private controller spool. Direct worker
  callbacks, URL credentials, broad request-limit exemptions, mutable live
  source reads, public ticket tools, and in-memory whole-transfer buffering are
  explicitly not being ported.

Pre-implementation measurement used a real loopback controller process and a
separate enrolled worker process. Each size was transferred twice by current
`session_copy` RPC and twice by a worker-side 1 MiB-chunk raw HTTP prototype;
all outputs were size/SHA-256 verified. Best observed times were:

| Bytes | Current RPC | Raw HTTP prototype | Speedup |
|---:|---:|---:|---:|
| 262,144 | 0.1292 s | 0.00271 s | 47.6x |
| 1,048,576 | 1.1524 s | 0.00257 s | 449.1x |
| 8,388,608 | 8.4851 s | 0.00592 s | 1433.1x |

The prototype intentionally measures transport overhead before final ticket,
digest, and fsync costs; it is not a correctness substitute. The large-file
threshold is therefore set conservatively to 1 MiB: 256 KiB remains on the
simpler RPC path, while the measured base64/control-channel cost is already
material at 1 MiB. The completed gateway will be benchmarked again before
closure.

Initial implementation/test plan: isolate durable gateway state and HTTP route
handling from `session_copy`; add source-only worker upload/download helpers and
an explicit `http-transfer-v1` capability; exempt only the exact transfer PUT
route from shared request buffering; add focused ticket/range/replay/snapshot/
quota/restart/cancellation/security tests; then run real one-worker and
two-worker E2E, full branch coverage, secret scan, cross-platform static gates,
pre-commit, push, and exact-head CI. Phase 9 remains out of scope.

Implementation checkpoint (2026-07-24):

- Added a private durable transfer store, Starlette-native controller routes,
  separate hashed header capabilities, worker/direction binding, TTL/claim/
  cursor state, immutable controller snapshots, disk-backed cross-worker spools,
  chunk and whole-object SHA-256 checks, exact durable replay handling, bounded
  Range/Content-Range, quota settings, and existing transactional destination
  commit/resume. No public MCP tool was added.
- Added source-only worker HTTP upload/download code using Python's standard
  library only, strict same-origin URL validation, status-based retry/resume,
  source identity verification, partial destination persistence, and explicit
  abort cleanup. Workers advertise `http-transfer-v1`; non-capable workers and
  sub-threshold files retain the RPC path, while same-worker copies keep their
  direct path.
- `SessionCopyOutput` now reports the truthful transport and resumed byte count.
  Managed background jobs use their durable job id as the private resume key;
  directory copies continue pack/copy/unpack and inherit the selected transport.
- Added validated config/CLI surface for enablement, 1 MiB threshold, 1 MiB
  chunks, five-minute grant TTL, active-transfer count, and total spool bytes.
  Shared request buffering is bypassed only for an exact validated private PUT
  route; every other route keeps the generic body limit.

Focused validation and defects found so far:

- Existing affected tests initially failed before server startup with
  `Setting spec mismatch` because the new settings were not registered in the
  config surface. The settings were added to the canonical config/CLI registry;
  the corrected existing focused set now passes `98 passed`.
- New gateway tests found that an unauthenticated HEAD request was classified as
  a missing direction (`422`) before authentication, and that the body-limit
  exemption also matched an empty transfer id. Authentication now fails first
  with `401`, and the exemption uses the exact 24-80 character identifier
  grammar. Gateway security/recovery tests now pass `11 passed`.
- The first real one-worker and two-worker E2E run reached the HTTP path but both
  failed with `HTTP 500`. The exact controller traceback was
  `AssertionError: fastapi_middleware_astack not found in request scope`; the
  root cause was inserting FastAPI `APIRoute` objects directly into the outer
  Starlette route table. The gateway was converted to native Starlette `Route`
  objects. The rerun passes both real-process tests, covering local-to-remote,
  remote-to-local, same-worker direct copy, and different-worker spool transfer.
- Targeted Ruff and full Pyright currently pass (`0 errors, 0 warnings`). The
  expanded focused set now passes `135 passed`; branch coverage is `98.21%` for
  `session_copy.py`, `95.72%` for `remote/transfer_gateway.py`, and `96.80%` for
  `remote_worker/http_transfer.py`.
- A retry-specific worker test exposed a real interrupted-upload defect: after a
  failed PUT, when controller status still reported the original cursor, the
  source file handle remained advanced and the next iteration falsely reported
  an early EOF. The worker now seeks to every authoritative controller cursor,
  including an unchanged cursor, before retrying the chunk. The worker HTTP set
  passes `6 passed`, gateway security/recovery/rollback tests pass `18 passed`,
  and session-copy selection/error/resume tests pass `11 passed`.
- Real-process E2E was extended to verify the measured threshold and directory
  path: large local/remote and two-worker file/directory copies use
  `http_stream`, sub-threshold files use `worker_rpc`, and same-worker copies use
  `same_worker`. Durable logs/exit markers are under
  `/tmp/local-shell-mcp-phase8-*`.
- The completed implementation was benchmarked again using separate real
  controller/worker runs with HTTP forced off versus normal transport
  selection, two verified copies per size. At 256 KiB the selected RPC path was
  0.1261 s versus 0.1078 s forced RPC (same transport/no claimed win). At 1 MiB
  final `http_stream` was 0.1491 s versus 1.1357 s forced RPC (7.62x), and at
  8 MiB it was 0.2688 s versus 8.5226 s (31.71x). This confirms the measured
  1 MiB default after authentication, snapshot, digest, fsync, spool, and atomic
  destination costs are included. Durable marker
  `/tmp/local-shell-mcp-phase8-final-benchmark.exit` is `0`.
- Permanent remote-worker, security, upstream-review, and fork-difference docs
  now describe the implemented transport and rejected upstream choices.
  Generated config examples and MCP references were refreshed; the public tool
  list remains exactly 40 tools before and after.
- Final static/document gates pass from a clean invocation: Ruff format/check,
  Pyright (`0 errors, 0 warnings`), `uv lock --check`, config/reference checks,
  release matrix, strict MkDocs, generated reference assets, and
  `git diff --check`.
- Repository secret scan reported one existing runtime-generated worker token
  assignment in `remote/manager.py` and existing fake-secret fixtures in
  unrelated secret-scan/agent-bridge tests. Targeted scans of all changed
  transfer/HTTP production and test files returned zero findings. Manual diff
  audit confirmed that plaintext transfer capabilities are neither persisted
  nor logged, never appear in URLs, argv, or service definitions, and exist only
  in the in-memory authenticated worker job payload needed to deliver the
  header. Persisted gateway metadata contains only hashes, session ids, bounded
  sizes/digests/cursors/timestamps/claims; no source absolute path or controller
  URL is stored. No service lifecycle or credential-bearing CLI was modified.
- The first clean full-suite attempt completed pytest but failed three repository
  contract tests: `3 failed, 1018 passed, 2 skipped`. Exact causes were missing
  public method/attribute docstrings on the new gateway dataclasses/store and
  missing local-private handler declarations for the three worker HTTP actions.
  No transfer behavior test failed. The dataclass/store documentation was added,
  and matching local-private handlers now delegate to the same source-only
  stdlib client without entering the public MCP registry. Contract/focused/E2E
  rerun passes `70 passed`; the public tool list remains exactly `40 -> 40` with
  identical names.
- A final manual TOCTOU pass found that a controller spool was no-follow checked
  but not persistently identity-bound across later append/download/publish opens.
  Gateway metadata now stores the platform-native spool identity created under
  the private lock; every resume, append, Range response, and local transaction
  reopens through the existing cross-platform secure file helpers and validates
  that identity before reading or writing. Symlink and same-user regular-file
  replacement are both rejected, and an attacker replacement file is proven
  unchanged. Open failures, write/fsync failures, and rollback failures now have
  distinct stable internal errors. Focused coverage after hardening passes
  `168 passed`: `session_copy.py` 98.21% branch,
  `remote/transfer_gateway.py` 93.22%, and
  `remote_worker/http_transfer.py` 96.80%.
  The subsequent full pytest run passed `1022 passed, 2 skipped`, and total
  branch coverage reached `86.03%`, but the per-module coverage ratchet rejected
  two precisely attributable gaps: `config/settings.py` was `96.97%` versus its
  `98.20%` floor, and the newly extended private
  `tools/registry/transfer.py` was `90.14%` versus `98.31%`. Direct tests now
  cover every new transfer-limit validation/config-file branch plus the three
  local-private HTTP handlers and existing abort wrapper; the focused correction
  passes `15 passed` with Ruff/Pyright clean. This was a coverage-policy failure,
  not a pytest behavior failure.
- The final clean rerun passes `1024 passed, 2 skipped`; durable marker
  `/tmp/local-shell-mcp-phase8-full-coverage.exit` is `0`. Total branch-mode
  coverage is `86.17%` against the `82.60%` baseline, and every module ratchet
  passes. Key final module coverage is: `config/settings.py` 100%,
  `tools/registry/transfer.py` 100%, `ops/utils/session_copy.py` 98.21%,
  `remote/transfer_gateway.py` 94.19%, and
  `remote_worker/http_transfer.py` 96.80%. A separate branch-only check for the
  new gateway is `148/164 = 90.24%`, satisfying the explicit Phase 8 branch
  target.
- Final targeted secret scans of changed transfer/HTTP production and test files
  return zero findings. Final full-repository pre-commit durable marker
  `/tmp/local-shell-mcp-phase8-precommit.exit` is `0`; Ruff check/format,
  generated config and tool references, VS Code format/lint/compile, and OpenTUI
  generated assets all pass.
- Main implementation `b9e649e627e3b70e457fa9936a5e92faa231f472` and
  checkpoint `371c97aeab73af7195b1f002f619592897b0c0d0` were pushed with
  origin divergence `0/0`. Exact-head Docs run `30059640530` passed. Exact-head
  CI run `30059640559` completed with `22/24` jobs successful; every non-test
  gate, Chromium, macOS tests, ConPTY, OpenTUI, VS Code, Docker, package smoke,
  platform wheel, bundled tmux, and release-matrix job passed. Ubuntu test job
  `89378494517` failed because unlink/recreate reused the same Linux inode and
  the replacement was safely rejected as `transfer spool size changed` before
  the test's narrower `identity changed` assertion. This exposed a real residual
  risk for a same-inode, same-size replacement, so the fix persists a third spool
  generation component derived from native ctime/mtime and refreshes it after
  every durable append or rollback. Windows test job `89378494518` showed that
  the prior CRT opener followed file symlinks: snapshot symlink rejection did
  not fire, while spool symlink replacement was only rejected after opening the
  target and comparing identity. Windows now opens path entries with
  `CreateFileW` plus `FILE_FLAG_OPEN_REPARSE_POINT`, rejects every reparse point
  before converting the native handle to a Python fd, and retains post-open
  identity/generation validation for TOCTOU. Focused fix validation passes
  `59 passed` with Ruff/Pyright clean. The final clean full-suite durable marker
  `/tmp/local-shell-mcp-phase8-ci-fix-full.exit` is `0`: `1026 passed, 2
  skipped`, total branch-mode coverage `86.19%`, and every module ratchet passes.
  Key coverage is `ops/transfer.py` 78.56%, `remote/transfer_gateway.py` 93.81%,
  `remote_worker/http_transfer.py` 96.80%, and `ops/utils/session_copy.py`
  98.21%; the gateway's separate pure branch check is again `148/164 = 90.24%`.
  Targeted secret scans of the changed transfer/gateway/test files are zero-findings;
  the only full-`src` heuristic match is the pre-existing runtime-generated worker
  token assignment in `remote/manager.py`, outside this fix. Strict MkDocs and
  generated reference checks pass. Final pre-commit durable marker
  `/tmp/local-shell-mcp-phase8-ci-fix-precommit.exit` is `0`, including Ruff,
  config/tool generation, VS Code, and OpenTUI asset hooks. Security fix
  `3e0e75a65f9b34f88385825ebd917c1347250a9e` was pushed with HEAD/origin
  divergence `0/0`. Exact-head Docs run `30061358592` passed. Exact-head CI run
  `30061358594` passed all `24/24` jobs, including the original Ubuntu and
  Windows failure platforms, macOS, Chromium, ConPTY, OpenTUI, VS Code, Docker,
  package smoke, every platform wheel, bundled tmux, and release matrix. Phase 8
  exit criteria are satisfied. Closure commit
  `9697a5b9727316a93acf838bf77ff4eada7455fe` was pushed with divergence `0/0`;
  exact-head CI run `30061677680` passed all `24/24` jobs. The commit changed only
  the temporary migration plan, so the Docs workflow was not triggered by its
  path filters. This final record commit now only requires its own exact-head CI.

Public API rule:

- Keep `session_copy` as the only public copy API. Do not expose ticket creation,
  upload, download, or transport-selection tools through MCP.
- Extend the result with a truthful transport indicator such as `local`,
  `same_worker`, `worker_rpc`, or `http_stream` and resumable byte progress where
  applicable.

Transport architecture:

- Add controller transfer-gateway routes under `/remote/transfer/`.
- URLs contain only a non-secret ticket identifier. A separate high-entropy
  transfer authorization value is sent in a header, is bound to one worker
  identity/direction/object, and is never logged or returned to MCP clients.
- Persist private, atomic, versioned ticket/spool metadata so a durable copy job
  can resume after controller restart. Enforce TTL, one active claim, offset,
  expected size, SHA-256, worker binding, and explicit revoke/abort/commit.
- Download tickets use an immutable private snapshot. Upload tickets write into
  an existing transactional destination or a private controller spool.
- Upload supports bounded `Content-Range` chunks and a status endpoint for
  resume. Download supports validated range resume and never follows a changed
  source path after ticket creation.
- Stream request/response chunks with independent byte, time, concurrency, and
  spool quotas. Exempt only these routes from shared body buffering and enforce
  all limits inside the route.

Routing behavior:

- local to local: existing direct transactional copy;
- same remote worker: existing worker-local fast path;
- local to remote: worker pulls an immutable controller download ticket and
  commits locally;
- remote to local: worker pushes to a controller upload ticket tied to the local
  transaction;
- different remote workers: source pushes to a private controller spool, then
  destination pulls the immutable spool; the controller brokers metadata and
  disk-backed streaming, not base64 JSON chunks;
- directories: continue bounded pack/stream/unpack semantics and clean all
  source/destination/spool archives on success, failure, cancellation, or expiry.

Selection and fallback:

- Add validated settings for enablement, large-file threshold (measured default
  1 MiB), ticket TTL (initial default five minutes), maximum active transfers,
  and spool bytes.
- Select HTTP only above the threshold and only when the worker advertises the
  capability. Keep RPC chunks for small transfers and as an explicit fallback
  when the gateway is unavailable.
- Capability fallback is protocol negotiation, not a removed-tool compatibility
  layer. Automatic upgrade should normally bring workers to the HTTP-capable
  bundle before selection.
- Background `session_copy` jobs persist enough arguments/progress to retry or
  resume safely; completed chunks are never silently duplicated.

Tests and measurements:

- Ticket entropy/header secrecy, auth, worker binding, TTL, claim races,
  revoke/abort, malformed ranges, offset conflicts, digest/size mismatch,
  immutable snapshots, symlink/source replacement, spool quotas, restart
  recovery, cancellation, and cleanup.
- Real worker E2E for local/remote, remote/local, same-worker, and two-worker
  routes with files and directories, including interrupted/resumed transfers.
- Verify generic request-body limits still protect every non-transfer route.
- Add repeatable RPC-vs-HTTP benchmarks at representative file sizes. Keep the
  feature only if HTTP materially reduces controller CPU/memory or transfer time;
  correctness tests remain mandatory regardless of benchmark outcome.

Exit criterion: large cross-machine `session_copy` avoids base64 control-channel
relay, resumes safely, preserves transactional semantics, and automatically
falls back for small or non-capable routes.

### Phase 9 — Final integration and permanent documentation

- Run the complete Linux/macOS/Windows suite, browser E2E, real remote-worker E2E,
  package smoke, platform-wheel smoke, OpenTUI matrix, VS Code jobs, Docker/
  Compose checks, release matrix, branch coverage ratchet, and bundled tmux smoke.
- Threat-model and document Agent Bridge credentials/OAuth, audit full-payload
  access, transfer tickets/spools, worker services, raw terminals, and embedded
  native wheel payloads.
- Update the product-difference report so all requested gaps are recorded as
  implemented/adapted, and document intentional remaining differences.
- Re-audit every upstream commit after the baseline ref and append it to the
  single chronological upstream review table.
- Generate final tool/config/instruction references and verify no removed
  compatibility names return.
- Record native artifact provenance, source version, licenses, hashes, supported
  platforms, and rebuild procedure for OpenTUI and bundled tmux.
- Replace temporary implementation notes with durable docs and delete this file
  in the final migration commit.

Exit criterion: this file has no unchecked implementation item, permanent docs
are authoritative, the branch is clean/synchronized, all required CI is green,
and deleting this temporary plan does not remove unique operational knowledge.

## Planned phase checklist

- [x] Phase 1: remove stale-tool diagnostics/tombstones.
- [x] Phase 2: real Chromium browser E2E.
- [x] Phase 3: Agent Bridge secrets and OAuth CLI/runtime.
- [x] Phase 4: structured environment in `session_start`.
- [x] Phase 5A: recoverable oversized audit payload store.
- [x] Phase 5B: session-bound MCP `audit_tail`.
- [x] Phase 6: Linux/macOS worker user-service management.
- [x] Phase 7: platform wheels with embedded OpenTUI.
- [x] Phase 8: internal resumable HTTP large-file transfer.
- [ ] Phase 9: full integration, permanent docs, and plan deletion.
