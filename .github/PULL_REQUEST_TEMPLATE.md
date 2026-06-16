## Summary

-

## Validation

- [ ] `uv run pre-commit run --all-files`
- [ ] `uv run pyright`
- [ ] `uv run pytest -q`
- [ ] `uv run mkdocs build --strict` if docs changed
- [ ] VS Code extension compile if extension files changed

## Safety checklist

- [ ] No credentials or private workspace data are committed.
- [ ] New or changed MCP/REST tools are documented and tested.
- [ ] Host-control, remote-worker, file-link, or credential behavior is described.
- [ ] Backwards compatibility impact is noted.
