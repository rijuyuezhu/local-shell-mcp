"""Directional guardrails for the runtime/dependency migration in issue #112."""

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[1]
_PACKAGE_ROOT = _PROJECT_ROOT / "src" / "local_shell_mcp"
_MIGRATION_DOC = (
    _PROJECT_ROOT / "docs" / "maintenance" / "runtime-architecture-migration.md"
)

# These are Phase 0 ceilings measured at commit 21e9bbeb (PR #111). They are
# intentionally one-way: migration PRs may shrink the values without updating
# this table, while increases require an explicit architecture decision.
_AMBIENT_GETTER_CEILINGS = {
    "get_settings(": (122, 52),
    "get_tool_session_store(": (82, 25),
    "get_state_store(": (29, 15),
}
_REMOTE_BRANCH_PATTERN = re.compile(
    r"\bsession\.target\s*(?:==|!=)\s*[\"']remote[\"']"
)
_REMOTE_BRANCH_CEILING = (43, 18)

_LIFECYCLE_INVENTORY = {
    "remote/manager.py": ("REMOTE_MANAGER",),
    "terminal/bridge.py": ("_BRIDGES", "_SHELL_BRIDGES", "_PENDING_SHELLS"),
    "jobs/managed.py": (
        "_MANAGED_JOB_HANDLERS",
        "_MANAGED_JOB_TASKS",
        "_MANAGED_JOB_LEASES",
    ),
    "ui/http/remote_files.py": ("_SESSION_CACHE",),
    "oauth/core/models.py": ("_CLIENTS", "_CODES"),
    "oauth/core/service.py": ("_AUTH_CODE_LOCK", "_OAUTH_CLIENT_LOCK"),
}


def _python_sources() -> list[Path]:
    return sorted(_PACKAGE_ROOT.rglob("*.py"))


def _count_literal(literal: str) -> tuple[int, int]:
    calls = 0
    files = 0
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        matches = text.count(literal)
        if matches:
            calls += matches
            files += 1
    return calls, files


def _count_remote_branches() -> tuple[int, int]:
    matches = 0
    files = 0
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        current = len(_REMOTE_BRANCH_PATTERN.findall(text))
        if current:
            matches += current
            files += 1
    return matches, files


def _assert_directional_ceiling(
    actual: tuple[int, int], ceiling: tuple[int, int], label: str
) -> None:
    actual_matches, actual_files = actual
    max_matches, max_files = ceiling
    assert actual_matches <= max_matches, (
        f"{label} grew from the Phase 0 ceiling of {max_matches} matches "
        f"to {actual_matches}; inject/resolve a narrow dependency instead of "
        "adding new ambient access, or document the exceptional architecture "
        "decision explicitly"
    )
    assert actual_files <= max_files, (
        f"{label} spread from the Phase 0 ceiling of {max_files} files "
        f"to {actual_files}; keep the migration directional"
    )


def test_ambient_dependency_access_only_shrinks_during_runtime_migration() -> (
    None
):
    for literal, ceiling in _AMBIENT_GETTER_CEILINGS.items():
        _assert_directional_ceiling(_count_literal(literal), ceiling, literal)


def test_direct_session_remote_branching_only_shrinks_during_runtime_migration() -> (
    None
):
    _assert_directional_ceiling(
        _count_remote_branches(),
        _REMOTE_BRANCH_CEILING,
        'session.target ==/!= "remote"',
    )


def test_lifecycle_bearing_process_state_is_kept_in_the_migration_inventory() -> (
    None
):
    documentation = _MIGRATION_DOC.read_text(encoding="utf-8")

    for relative_path, symbols in _LIFECYCLE_INVENTORY.items():
        assert f"`{relative_path}" in documentation
        source = (_PACKAGE_ROOT / relative_path).read_text(encoding="utf-8")
        for symbol in symbols:
            # As each state owner is migrated, remove it from this inventory and
            # this test in the same PR. Until then, the symbol must remain both
            # real and explicitly classified rather than silently drifting.
            assert symbol in source
            assert f"`{symbol}`" in documentation
