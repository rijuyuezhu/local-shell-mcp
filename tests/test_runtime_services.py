from local_shell_mcp.config.settings import Settings
from local_shell_mcp.executors.runtime_services import (
    configure_runtime_services,
)
from local_shell_mcp.persistence import configure_state_store, get_state_store
from local_shell_mcp.tool_session import (
    configure_tool_session_store,
    get_tool_session_store,
)


def test_runtime_services_install_explicit_store_dependencies(tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / ".state",
    )

    services = configure_runtime_services(settings)
    try:
        assert get_state_store() is services.state_store
        assert get_tool_session_store() is services.tool_session_store
        assert services.state_store.layout.root == settings.state_dir
        assert services.tool_session_store._settings() is settings
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)
