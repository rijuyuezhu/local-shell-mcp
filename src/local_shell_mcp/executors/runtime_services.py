"""Process service composition for server executors."""

from dataclasses import dataclass

from ..config.settings import Settings
from ..persistence import FileStateStore, configure_state_store
from ..tool_session import configure_tool_session_store
from ..tool_session.store import ToolSessionStore


@dataclass(frozen=True)
class RuntimeServices:
    """Explicit process-wide services shared by server execution surfaces."""

    state_store: FileStateStore
    tool_session_store: ToolSessionStore


def configure_runtime_services(settings: Settings) -> RuntimeServices:
    """Construct and install stateful runtime services for one resolved config."""
    state_store = FileStateStore(lambda: settings.state_dir)
    tool_session_store = ToolSessionStore(
        state_store=state_store,
        settings_provider=lambda: settings,
    )
    configure_state_store(state_store)
    configure_tool_session_store(tool_session_store)
    return RuntimeServices(
        state_store=state_store,
        tool_session_store=tool_session_store,
    )
