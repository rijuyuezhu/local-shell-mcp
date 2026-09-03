import pytest

from local_shell_mcp.config.settings import clear_settings_cache


@pytest.fixture(autouse=True)
def isolated_runtime_paths(monkeypatch, tmp_path):
    state_dir = tmp_path / ".local-shell-mcp"
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
async def managed_jobs_runtime_owner():
    from local_shell_mcp.jobs import recovery as job_recovery
    from local_shell_mcp.jobs.managed import (
        ManagedJobsRuntime,
        configure_managed_jobs_runtime,
    )
    from local_shell_mcp.ops.utils.session_copy import (
        session_copy_managed_job_registration,
    )

    runtime = ManagedJobsRuntime()
    kind, handler = session_copy_managed_job_registration()
    runtime.register_handler(kind, handler)
    await runtime.start()
    previous = configure_managed_jobs_runtime(runtime)
    job_recovery.reset_deferred_sequence_for_tests()
    try:
        yield runtime
    finally:
        try:
            await runtime.aclose()
        finally:
            configure_managed_jobs_runtime(previous)
            job_recovery.reset_deferred_sequence_for_tests()
