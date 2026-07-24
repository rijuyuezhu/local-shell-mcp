# Development

This page is for contributors working on `local-shell-mcp` itself. It focuses on how to run, debug, test, and regenerate docs without relying on stale code walkthroughs.

## Local environment

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
uv run pre-commit install
```

## Run the server during development

Run MCP-over-HTTP locally without OAuth:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode mcp --port 13444
```

Run the REST debug API locally without OAuth:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none uv run local-shell-mcp --mode http --port 13444
```

Use an explicit workspace when needed:

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/project \
LOCAL_SHELL_MCP_AUTH_MODE=none \
uv run local-shell-mcp --mode http --port 13444
```

Use full-control mode only for disposable test workspaces:

```bash
LOCAL_SHELL_MCP_AUTH_MODE=none \
uv run local-shell-mcp --mode http --port 13444 --allow-full-control true
```

## Smoke-test with curl

Health check:

```bash
curl -i http://127.0.0.1:13444/healthz
```

Inspect environment through the REST debug API:

```bash
curl -s -X POST http://127.0.0.1:13444/tools/session_start \
  -H 'content-type: application/json' \
  -d '{"workdir":"."}' | jq
```

Read a file through the REST debug API:

```bash
curl -s -X POST http://127.0.0.1:13444/tools/read \
  -H 'content-type: application/json' \
  -d '{"path":"README.md:1-40"}' | jq
```

List files:

```bash
curl -s -X POST http://127.0.0.1:13444/tools/list_files \
  -H 'content-type: application/json' \
  -d '{"path":".","max_entries":20}' | jq
```

Export the MCP tool surface:

```bash
uv run python scripts/export-tools-json.py --wrapped > /tmp/local-shell-mcp-tools.json
jq '.count, [.tools[].name]' /tmp/local-shell-mcp-tools.json
```

## Watch logs and audit output

For a foreground dev process, read the terminal output first.

For a user systemd service:

```bash
journalctl --user -u local-shell-mcp.service -f -n 200
```

Audit log:

```bash
tail -F /workspace/.local-shell-mcp/audit_log/audit.jsonl | jq -C --unbuffered .
```

Audit state can contain prompts, tool inputs, tool outputs, file contents, bounded JSONL previews, and recoverable sanitized payload objects. Credential-like values are redacted on a best-effort basis before storage, but both JSONL and the payload directory must still be treated as sensitive.

## Architecture boundaries

The package is layered around transport-neutral tool behavior. Keep dependency
direction explicit when adding features or moving code:

- `config`, `schemas`, and small `utils` modules provide dependency-leaf
  settings, contracts, serialization, and filesystem primitives.
- `agent_bridge`, `remote`, `remote_worker`, and `tool_session` own their domain
  state and protocols. Source-only worker modules must remain usable without the
  controller's full dependency stack.
- `ops` implements transport-neutral use cases. It may use domain services and
  schemas, but it must not depend on HTTP, MCP, or Human UI adapters.
- `tools` owns public tool contracts, discovery, metadata, and registration.
- `http` owns executor-neutral Starlette/ASGI infrastructure shared by REST and
  MCP-over-HTTP. It must not import an executor or Human UI implementation.
- `executors/mcp` owns MCP composition, MCP-specific middleware, and stdio or
  MCP-over-HTTP runtime selection.
- `executors/http` owns REST tool routes, REST error and timeout policy, and the
  runnable FastAPI application.
- `ui/http` owns Human UI HTTP and WebSocket adapters. The REST executor may
  import only its explicit route-composition contract; lower layers must not
  import executors or UI delivery adapters. The obsolete `server` package has
  been removed and must not be restored.
- `main` is the process-composition entry point and is allowed to select
  executors.

Human UI route handlers should validate transport input and delegate reusable
behavior to `ops` or domain services. MCP-facing annotations and OAuth security
metadata are tool presentation contracts, not transport implementation details.
Avoid generic service locators: extract small dependency-leaf contracts and
explicit facades instead. See [Architecture and module ownership](architecture.md)
for the file-by-file ownership map and rejected placement alternatives.

`tests/test_architecture.py` enforces current dependency cycles, explicit
executor/UI composition imports, and dependency-leaf package boundaries. Its
allowlists are visible technical debt, not extension points: when a cycle or reversed import is
removed, shrink the allowlist in the same change. New entries require an explicit
architecture review.

## Run checks before committing

```bash
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
uv run mkdocs build --strict
```

For focused work, run the relevant subset first:

```bash
uv run pytest tests/test_tool_surface.py -q
uv run pytest tests/test_config_surface.py -q
uv run pytest tests/test_agent_bridge_tools.py -q
```

## Check branch coverage

The Ubuntu CI job runs the complete Python suite under branch coverage. It
ratchets both the aggregate percentage and every existing source file against
`scripts/coverage-baseline.json`; a new non-empty module must begin at 90%
coverage. The committed baseline records the lowest value observed for each
module across the local Linux and GitHub Ubuntu reports, so environment-only
branches cannot make either supported run flaky. Run the same gate locally
with:

```bash
find . -maxdepth 1 -name '.coverage*' -delete
uv run python -m coverage run -m pytest -q
uv run python -m coverage combine
uv run python -m coverage json
uv run python -m coverage xml
uv run python -m coverage report
uv run python scripts/check-coverage.py
```

Only update the baseline after reviewing why coverage changed. Download the
`python-coverage` artifact from the Ubuntu job for the same source revision,
then merge it with the local report. The checker rejects different source sets
or statement/branch counts, and stores the per-module and aggregate minima:

```bash
gh run download <run-id> -n python-coverage -D /tmp/python-coverage
uv run python scripts/check-coverage.py \
  --write-baseline \
  --report coverage.json \
  --report /tmp/python-coverage/coverage.json
```

Coverage regressions should instead gain tests or be explicitly justified in
review.

## Regenerate generated reference data

Configuration examples and reference JSON are generated from the settings registry:

```bash
uv run python scripts/generate-config-examples.py
uv run python scripts/generate-config-examples.py --check
```

Tool and instruction reference JSON are generated from the live MCP app:

```bash
uv run python scripts/export-tools-json.py \
  --wrapped \
  --output docs/reference/generated/tools.json \
  --instructions-output docs/reference/generated/server-instructions.json

uv run python scripts/export-tools-json.py \
  --wrapped \
  --output docs/reference/generated/tools.json \
  --instructions-output docs/reference/generated/server-instructions.json \
  --check
```

The pre-commit hooks run these generators when related source files change.

## Documentation development

The documentation site uses Material for MkDocs.

```bash
uv sync --group docs
uv run mkdocs serve
uv run mkdocs build --strict
```

## Release checks

Before cutting a release:

```bash
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
uv run mkdocs build --strict
uv run python scripts/check-release-matrix.py
uv build --out-dir dist
```

The ordinary `uv build` output must contain exactly one payload-free universal
`py3-none-any` wheel and one source-only sdist. Native OpenTUI wheels are built
only on matching runners with the pinned Bun release, for example:

```bash
uv run python scripts/build-platform-wheel.py \
  --platform-tag linux_x86_64 \
  --output-dir dist
```

The builder accepts only the repository's explicit target tags, validates the
native host and executable magic, creates deterministic gzip metadata, rewrites
and verifies `WHEEL` plus `RECORD`, and removes staging files on success or
failure. Release CI installs every platform wheel in an isolated environment
with Bun and sidecars absent, then runs `scripts/smoke-platform-wheel.py` before
all Python package artifacts are published together. Native source, license,
platform, rebuild, and checksum ownership is recorded in
[Native artifact provenance](maintenance/native-artifact-provenance.md). Run
`uv run python scripts/check-native-provenance.py` whenever those inputs change.

Also test the Docker image or binary artifact and at least one real MCP connection path before publishing.

