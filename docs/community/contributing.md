# Contributing

Thanks for improving `workgate`. Keep changes focused, tested, and aligned with the current Python 3.14 architecture.

## Development checks

```bash
uv sync --locked --group dev --group docs
uv run pre-commit run --all-files
uv run pyright
uv run pytest -q
uv run mkdocs build --strict
```

## Architecture guidelines

- Keep concrete behavior in `src/workgate/ops/`.
- Expose tools through `src/workgate/tools/registry/` and the declarative registry unless a dynamic surface is required.
- Keep server assembly in `src/workgate/server/`.
- Keep remote-worker behavior in `src/workgate/remote/`.
- Use Python 3.14 syntax directly; do not add compatibility imports such as `from __future__ import annotations`.
