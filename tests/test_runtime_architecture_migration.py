"""Directional guardrails for the runtime/dependency migration in issue #112."""

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[1]
_PACKAGE_ROOT = _PROJECT_ROOT / "src" / "local_shell_mcp"
# These ceilings were tightened at the end of issue #112 to the post-migration
# baseline. They are intentionally one-way: later changes may shrink the values
# without updating this table, while increases require an explicit architecture
# decision.
_AMBIENT_GETTER_CEILINGS = {
    "get_settings(": (114, 52),
    "get_tool_session_store(": (68, 24),
    "get_state_store(": (29, 15),
}
_REMOTE_BRANCH_PATTERN = re.compile(
    r"\bsession\.target\s*(?:==|!=)\s*[\"']remote[\"']"
)
_REMOTE_BRANCH_CEILING = (35, 15)


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


def test_managed_jobs_live_state_is_controller_owned_and_reconciliation_is_pure() -> (
    None
):
    managed_source = (_PACKAGE_ROOT / "jobs" / "managed.py").read_text(
        encoding="utf-8"
    )
    reconciliation_source = (
        _PACKAGE_ROOT / "jobs" / "reconciliation.py"
    ).read_text(encoding="utf-8")
    controller_source = (_PACKAGE_ROOT / "executors" / "runtime.py").read_text(
        encoding="utf-8"
    )
    worker_source = (
        _PACKAGE_ROOT / "remote_worker" / "runtime_composition.py"
    ).read_text(encoding="utf-8")
    session_copy_source = (
        _PACKAGE_ROOT / "ops" / "utils" / "session_copy.py"
    ).read_text(encoding="utf-8")

    for symbol in (
        "_MANAGED_JOB_HANDLERS",
        "_MANAGED_JOB_TASKS",
        "_MANAGED_JOB_LEASES",
    ):
        assert symbol not in managed_source
    assert "reset_managed_jobs_for_tests" not in managed_source
    assert "class ManagedJobsRuntime" in managed_source
    assert "managed_jobs_runtime: ManagedJobsRuntime" in controller_source
    assert "ManagedJobsRuntime()" in controller_source
    assert "ManagedJobsRuntime" not in worker_source
    assert "session_copy_managed_job_registration" in controller_source
    assert "register_managed_job_handler(SESSION_COPY_MANAGED_KIND" not in (
        session_copy_source
    )
    assert "def reconcile_job(" in reconciliation_source
    assert "get_settings(" not in reconciliation_source
    assert "get_tool_session_store(" not in reconciliation_source
    controller_close_source = controller_source.split(
        "    async def aclose(self) -> None:", 1
    )[1].split("    @asynccontextmanager", 1)[0]
    assert controller_close_source.index(
        "await self.managed_jobs_runtime.aclose()"
    ) < controller_close_source.index("await self.human_ui_runtime.aclose()")


def test_remote_manager_is_controller_owned_not_a_module_singleton() -> None:
    manager_source = (_PACKAGE_ROOT / "remote" / "manager.py").read_text(
        encoding="utf-8"
    )
    runtime_source = (_PACKAGE_ROOT / "executors" / "runtime.py").read_text(
        encoding="utf-8"
    )

    assert (
        re.search(r"^REMOTE_MANAGER\s*=", manager_source, re.MULTILINE) is None
    )
    assert "remote_manager: RemoteManager" in runtime_source
    assert "RemoteManager(" in runtime_source


def test_terminal_live_state_is_runtime_owned_not_module_registry_maps() -> (
    None
):
    bridge_source = (_PACKAGE_ROOT / "terminal" / "bridge.py").read_text(
        encoding="utf-8"
    )
    conpty_source = (_PACKAGE_ROOT / "terminal" / "conpty.py").read_text(
        encoding="utf-8"
    )
    terminal_runtime_source = (
        _PACKAGE_ROOT / "terminal" / "runtime.py"
    ).read_text(encoding="utf-8")
    controller_source = (_PACKAGE_ROOT / "executors" / "runtime.py").read_text(
        encoding="utf-8"
    )
    worker_source = (
        _PACKAGE_ROOT / "remote_worker" / "runtime_composition.py"
    ).read_text(encoding="utf-8")

    for symbol in ("_BRIDGES", "_SHELL_BRIDGES", "_PENDING_SHELLS"):
        assert symbol not in bridge_source
    assert re.search(r"^_SESSIONS\s*[:=]", conpty_source, re.MULTILINE) is None
    assert "reset_terminal_bridges_for_tests" not in bridge_source
    assert "reset_conpty_sessions_for_tests" not in conpty_source
    assert "terminal_runtime: TerminalRuntime" in controller_source
    assert "terminal_runtime: TerminalRuntime" in worker_source
    assert "build_terminal_runtime()" in controller_source
    assert "build_terminal_runtime()" in worker_source
    assert terminal_runtime_source.index("await self.bridges.aclose()") < (
        terminal_runtime_source.index("await self.conpty.aclose()")
    )


def test_human_ui_live_state_is_controller_owned_not_module_registry_maps() -> (
    None
):
    terminals_source = (
        _PACKAGE_ROOT / "ui" / "http" / "terminals.py"
    ).read_text(encoding="utf-8")
    remote_files_source = (
        _PACKAGE_ROOT / "ui" / "http" / "remote_files.py"
    ).read_text(encoding="utf-8")
    live_state_source = (
        _PACKAGE_ROOT / "ui" / "http" / "live_state.py"
    ).read_text(encoding="utf-8")
    controller_source = (_PACKAGE_ROOT / "executors" / "runtime.py").read_text(
        encoding="utf-8"
    )

    for symbol in ("_CONNECTION_IDS", "_ACTIVE_CONNECTIONS"):
        assert symbol not in terminals_source
    for symbol in ("_SESSION_CACHE", "_MACHINE_LOCKS"):
        assert symbol not in remote_files_source
    assert "clear_ui_remote_file_sessions" not in remote_files_source
    assert "human_ui_runtime: HumanUiRuntime" in controller_source
    assert "build_human_ui_runtime(remote_manager.call)" in controller_source
    assert "class UiTerminalConnectionRegistry" in live_state_source
    assert "class UiRemoteFileSessionRegistry" in live_state_source
    assert controller_source.index("await self.human_ui_runtime.aclose()") < (
        controller_source.index("await self.oauth_state.aclose()")
    )
    assert controller_source.index("await self.oauth_state.aclose()") < (
        controller_source.index("await self.remote_manager.aclose()")
    )
    assert controller_source.index("await self.remote_manager.aclose()") < (
        controller_source.index("await self.terminal_runtime.aclose()")
    )


def test_oauth_live_state_is_controller_owned_not_module_registry_maps() -> (
    None
):
    models_source = (_PACKAGE_ROOT / "oauth" / "core" / "models.py").read_text(
        encoding="utf-8"
    )
    service_source = (
        _PACKAGE_ROOT / "oauth" / "core" / "service.py"
    ).read_text(encoding="utf-8")
    state_source = (_PACKAGE_ROOT / "oauth" / "core" / "state.py").read_text(
        encoding="utf-8"
    )
    routes_source = (_PACKAGE_ROOT / "oauth" / "http" / "routes.py").read_text(
        encoding="utf-8"
    )
    controller_source = (_PACKAGE_ROOT / "executors" / "runtime.py").read_text(
        encoding="utf-8"
    )

    for symbol in ("_CLIENTS", "_CODES"):
        assert symbol not in models_source
    for symbol in ("_AUTH_CODE_LOCK", "_OAUTH_CLIENT_LOCK"):
        assert symbol not in service_source
    assert "class OAuthState" in state_source
    assert "oauth_state: OAuthState" in controller_source
    assert "build_oauth_state(settings.state_dir)" in controller_source
    assert "initialize_dynamic_clients" not in routes_source


def test_files_vertical_uses_explicit_service_composition() -> None:
    files_source = (_PACKAGE_ROOT / "ops" / "files.py").read_text(
        encoding="utf-8"
    )
    service_source = (_PACKAGE_ROOT / "ops" / "files_service.py").read_text(
        encoding="utf-8"
    )
    read_source = (_PACKAGE_ROOT / "ops" / "read.py").read_text(
        encoding="utf-8"
    )
    controller_source = (
        _PACKAGE_ROOT / "executors" / "search_composition.py"
    ).read_text(encoding="utf-8")
    worker_source = (
        _PACKAGE_ROOT / "remote_worker" / "search_composition.py"
    ).read_text(encoding="utf-8")

    assert files_source.count("get_settings(") == 1
    assert files_source.count("get_tool_session_store(") == 1
    assert "get_settings(" not in service_source
    assert "get_tool_session_store(" not in service_source
    assert "get_settings(" not in read_source
    assert "get_tool_session_store(" not in read_source
    assert "FilesService(" in controller_source
    assert '"files": files_registry' in controller_source
    assert '"read": read_registry' in controller_source
    assert "FilesService(" in worker_source
    for tool_name in (
        "list_files",
        "write_file",
        "edit_lines",
        "hashline_edit",
        "delete_file_or_dir",
        "read",
    ):
        assert f'"{tool_name}"' in worker_source
