"""OAuth scope constants shared by metadata and authorization helpers."""

SCOPE_SHELL_READ = "shell:read"
SCOPE_SHELL_WRITE = "shell:write"
SCOPE_SHELL_EXECUTE = "shell:execute"
SCOPE_GIT_WRITE = "git:write"
SCOPE_FILE_SHARE = "file:share"
SCOPE_REMOTE_USE = "remote:use"

SUPPORTED_OAUTH_SCOPES = (
    SCOPE_SHELL_READ,
    SCOPE_SHELL_WRITE,
    SCOPE_SHELL_EXECUTE,
    SCOPE_GIT_WRITE,
    SCOPE_FILE_SHARE,
    SCOPE_REMOTE_USE,
)


SUPPORTED_OAUTH_SCOPE_SET = frozenset(SUPPORTED_OAUTH_SCOPES)


def dedupe_scopes(scopes: list[str] | tuple[str, ...]) -> list[str]:
    """Return scopes in input order without duplicates."""
    return list(dict.fromkeys(scopes))


def normalize_requested_scope(scope: str | None) -> str:
    """Return a normalized supported scope string, or raise ValueError."""
    if scope is None or not scope.strip():
        return " ".join(SUPPORTED_OAUTH_SCOPES)
    requested = dedupe_scopes(scope.split())
    unsupported = [
        item for item in requested if item not in SUPPORTED_OAUTH_SCOPE_SET
    ]
    if unsupported:
        raise ValueError(f"Unsupported scope: {unsupported[0]}")
    return " ".join(requested)


def scope_set(scope: str | None) -> set[str]:
    """Parse a space-delimited scope claim into a set."""
    return set((scope or "").split())
