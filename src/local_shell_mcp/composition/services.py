"""Shared construction and compatibility installation of process services."""

from dataclasses import dataclass

from ..config.settings import Settings
from ..persistence import FileStateStore, StateStore, configure_state_store
from ..tool_session import configure_tool_session_store
from ..tool_session.store import ToolSessionStore


@dataclass(frozen=True)
class RuntimeServices:
    """Explicit process-wide state services shared by long-lived runtimes."""

    state_store: FileStateStore
    """Configured durable process state store."""
    tool_session_store: ToolSessionStore
    """Configured authoritative tool-session store."""


@dataclass
class RuntimeServiceInstallation:
    """One reversible compatibility-global installation owned by a runtime."""

    previous_state_store: StateStore | None
    """State-store binding that was active before this installation."""
    previous_tool_session_store: ToolSessionStore | None
    """Tool-session binding that was active before this installation."""
    _active: bool = True

    def close(self) -> None:
        """Restore the previous compatibility bindings exactly once."""
        if not self._active:
            return
        configure_tool_session_store(self.previous_tool_session_store)
        configure_state_store(self.previous_state_store)
        self._active = False


def build_runtime_services(settings: Settings) -> RuntimeServices:
    """Construct shared state services without mutating process-global bindings."""
    state_store = FileStateStore(lambda: settings.state_dir)
    tool_session_store = ToolSessionStore(
        state_store=state_store,
        settings_provider=lambda: settings,
    )
    return RuntimeServices(
        state_store=state_store,
        tool_session_store=tool_session_store,
    )


def install_runtime_services(
    services: RuntimeServices,
) -> RuntimeServiceInstallation:
    """Install compatibility accessors for one already-constructed runtime graph."""
    previous_state_store = configure_state_store(services.state_store)
    try:
        previous_tool_session_store = configure_tool_session_store(
            services.tool_session_store
        )
    except BaseException:
        configure_state_store(previous_state_store)
        raise
    return RuntimeServiceInstallation(
        previous_state_store=previous_state_store,
        previous_tool_session_store=previous_tool_session_store,
    )


def configure_runtime_services(settings: Settings) -> RuntimeServices:
    """Compatibility facade that constructs and permanently installs services."""
    services = build_runtime_services(settings)
    install_runtime_services(services)
    return services
