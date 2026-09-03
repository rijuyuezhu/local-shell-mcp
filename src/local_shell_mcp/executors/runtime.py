"""Controller composition owner for long-lived server processes."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from ..composition.services import (
    RuntimeServiceInstallation,
    RuntimeServices,
    build_runtime_services,
    install_runtime_services,
)
from ..config.settings import Settings
from ..remote.manager import (
    RemoteManager,
    configure_remote_manager,
)
from ..tools.catalog import ToolCatalog
from .search_composition import build_controller_tool_catalog


@dataclass
class ControllerRuntime:
    """Own the controller's composed services and compatibility lifecycle."""

    settings: Settings
    """Resolved server settings for this controller process."""
    services: RuntimeServices
    """Explicit shared state services owned by this runtime."""
    remote_manager: RemoteManager
    """Controller-owned live remote-worker control-plane state."""
    tool_catalog: ToolCatalog
    """Controller tool catalog with the migrated Search service already bound."""
    _installation: RuntimeServiceInstallation | None = field(
        default=None, init=False, repr=False
    )
    _previous_remote_manager: RemoteManager | None = field(
        default=None, init=False, repr=False
    )
    _remote_binding_installed: bool = field(
        default=False, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        """Install compatibility bindings inside the owning async lifespan."""
        if self._closed:
            raise RuntimeError(
                "ControllerRuntime cannot be restarted after close"
            )
        if self._installation is not None:
            return
        installation = install_runtime_services(self.services)
        remote_started = False
        try:
            await self.remote_manager.start()
            remote_started = True
            previous_remote_manager = configure_remote_manager(
                self.remote_manager
            )
        except BaseException:
            try:
                if remote_started:
                    await self.remote_manager.aclose()
            finally:
                installation.close()
                self._closed = True
            raise
        self._installation = installation
        self._previous_remote_manager = previous_remote_manager
        self._remote_binding_installed = True

    async def aclose(self) -> None:
        """Restore prior compatibility bindings; repeated close is harmless."""
        installation = self._installation
        self._installation = None
        self._closed = True
        try:
            await self.remote_manager.aclose()
        finally:
            if self._remote_binding_installed:
                configure_remote_manager(self._previous_remote_manager)
                self._remote_binding_installed = False
                self._previous_remote_manager = None
            if installation is not None:
                installation.close()

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[ControllerRuntime]:
        """Run the controller ownership scope with deterministic cleanup."""
        try:
            await self.start()
            yield self
        finally:
            await self.aclose()


def build_controller_runtime(settings: Settings) -> ControllerRuntime:
    """Construct one controller graph without installing process globals yet."""
    services = build_runtime_services(settings)
    remote_manager = RemoteManager(
        lambda: settings,
        state_store=services.state_store,
    )
    return ControllerRuntime(
        settings=settings,
        services=services,
        remote_manager=remote_manager,
        tool_catalog=build_controller_tool_catalog(
            settings,
            services.tool_session_store,
            remote_manager,
        ),
    )
