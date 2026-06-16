# Contributing

Thanks for improving `local-shell-mcp`. Keep changes focused, tested, and aligned with the current Python 3.14 architecture.

## Development checks

```bash
uv sync --locked --group dev --group docs
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
uv run mkdocs build --strict
```

## Architecture guidelines

- Keep concrete behavior in `src/local_shell_mcp/ops/`.
- Expose tools through `src/local_shell_mcp/tools/registry/` and the declarative registry unless a dynamic surface is required.
- Keep server assembly in `src/local_shell_mcp/server/`.
- Keep remote-worker behavior in `src/local_shell_mcp/remote/`.
- Use Python 3.14 syntax directly; do not add compatibility imports such as `from __future__ import annotations`.
