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


def dedupe_scopes(scopes: list[str] | tuple[str, ...]) -> list[str]:
    """Return scopes in input order without duplicates."""
    return list(dict.fromkeys(scopes))
