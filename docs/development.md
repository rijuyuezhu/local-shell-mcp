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
curl -s http://127.0.0.1:13444/tools/environment_info | jq
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

The audit log can contain full prompts, tool inputs, tool outputs, and file contents. Treat it as sensitive.

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
```

Also test the Docker image or binary artifact and at least one real MCP connection path before publishing.

