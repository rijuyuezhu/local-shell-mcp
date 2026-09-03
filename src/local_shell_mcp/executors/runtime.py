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
from ..terminal.runtime import TerminalRuntime, build_terminal_runtime
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
    terminal_runtime: TerminalRuntime
    """Controller-owned terminal bridge and ConPTY live state."""
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
        terminal_started = False
        remote_started = False
        try:
            await self.terminal_runtime.start()
            terminal_started = True
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
                try:
                    if terminal_started:
                        await self.terminal_runtime.aclose()
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
        remote_error: BaseException | None = None
        terminal_error: BaseException | None = None
        try:
            try:
                await self.remote_manager.aclose()
            except BaseException as exc:
                remote_error = exc
            try:
                await self.terminal_runtime.aclose()
            except BaseException as exc:
                terminal_error = exc
        finally:
            if self._remote_binding_installed:
                configure_remote_manager(self._previous_remote_manager)
                self._remote_binding_installed = False
                self._previous_remote_manager = None
            if installation is not None:
                installation.close()
        if remote_error is not None:
            raise remote_error
        if terminal_error is not None:
            raise terminal_error

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
    terminal_runtime = build_terminal_runtime()
    return ControllerRuntime(
        settings=settings,
        services=services,
        remote_manager=remote_manager,
        terminal_runtime=terminal_runtime,
        tool_catalog=build_controller_tool_catalog(
            settings,
            services.tool_session_store,
            remote_manager,
        ),
    )
