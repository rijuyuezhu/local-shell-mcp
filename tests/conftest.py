import pytest

from workgate.config.settings import clear_settings_cache


def _reset_managed_deferred_sequence(job_recovery) -> None:
    with job_recovery._MANAGED_DEFERRED_SEQUENCE_LOCK:
        job_recovery._MANAGED_DEFERRED_NEXT_SEQUENCE = None


@pytest.fixture(autouse=True)
def isolated_runtime_paths(monkeypatch, tmp_path):
    state_dir = tmp_path / ".workgate"
    monkeypatch.setenv("WORKGATE_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("WORKGATE_STATE_DIR", str(state_dir))
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
async def managed_jobs_runtime_owner():
    from workgate.jobs import recovery as job_recovery
    from workgate.jobs.managed import (
        ManagedJobsRuntime,
        configure_managed_jobs_runtime,
    )
    from workgate.ops.utils.session_copy import (
        session_copy_managed_job_registration,
    )

    runtime = ManagedJobsRuntime()
    kind, handler = session_copy_managed_job_registration()
    runtime.register_handler(kind, handler)
    await runtime.start()
    previous = configure_managed_jobs_runtime(runtime)
    _reset_managed_deferred_sequence(job_recovery)
    try:
        yield runtime
    finally:
        try:
            await runtime.aclose()
        finally:
            configure_managed_jobs_runtime(previous)
            _reset_managed_deferred_sequence(job_recovery)
