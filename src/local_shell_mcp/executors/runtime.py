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
from ..tools.catalog import ToolCatalog
from .search_composition import build_controller_tool_catalog


@dataclass
class ControllerRuntime:
    """Own the controller's composed services and compatibility lifecycle."""

    settings: Settings
    """Resolved server settings for this controller process."""
    services: RuntimeServices
    """Explicit shared state services owned by this runtime."""
    tool_catalog: ToolCatalog
    """Controller tool catalog with the migrated Search service already bound."""
    _installation: RuntimeServiceInstallation | None = field(
        default=None, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        """Install compatibility bindings inside the owning async lifespan."""
        if self._closed:
            raise RuntimeError(
                "ControllerRuntime cannot be restarted after close"
            )
        if self._installation is None:
            self._installation = install_runtime_services(self.services)

    async def aclose(self) -> None:
        """Restore prior compatibility bindings; repeated close is harmless."""
        installation = self._installation
        self._installation = None
        self._closed = True
        if installation is not None:
            installation.close()

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[ControllerRuntime]:
        """Run the controller ownership scope with deterministic cleanup."""
        await self.start()
        try:
            yield self
        finally:
            await self.aclose()


def build_controller_runtime(settings: Settings) -> ControllerRuntime:
    """Construct one controller graph without installing process globals yet."""
    services = build_runtime_services(settings)
    return ControllerRuntime(
        settings=settings,
        services=services,
        tool_catalog=build_controller_tool_catalog(
            settings, services.tool_session_store
        ),
    )
