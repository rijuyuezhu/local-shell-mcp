"""Worker composition owner for the long-lived remote worker process."""

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
from ..terminal.runtime import TerminalRuntime, build_terminal_runtime
from .dispatch import WorkerDispatcher
from .search_composition import build_worker_dispatcher_with_search


@dataclass
class WorkerRuntime:
    """Own the worker's composed services and compatibility lifecycle."""

    settings: Settings
    """Resolved worker-compatible settings for this process."""
    services: RuntimeServices
    """Explicit shared state services owned by this worker."""
    terminal_runtime: TerminalRuntime
    """Worker-owned terminal bridge and ConPTY live state."""
    dispatcher: WorkerDispatcher
    """Worker dispatcher with the migrated Search service already bound."""
    _installation: RuntimeServiceInstallation | None = field(
        default=None, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        """Install compatibility bindings inside the worker's owning loop."""
        if self._closed:
            raise RuntimeError("WorkerRuntime cannot be restarted after close")
        if self._installation is not None:
            return
        installation = install_runtime_services(self.services)
        try:
            await self.terminal_runtime.start()
        except BaseException:
            installation.close()
            self._closed = True
            raise
        self._installation = installation

    async def aclose(self) -> None:
        """Restore prior compatibility bindings; repeated close is harmless."""
        installation = self._installation
        self._installation = None
        self._closed = True
        try:
            await self.terminal_runtime.aclose()
        finally:
            if installation is not None:
                installation.close()

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[WorkerRuntime]:
        """Run the worker ownership scope with deterministic cleanup."""
        try:
            await self.start()
            yield self
        finally:
            await self.aclose()


def build_worker_runtime(settings: Settings) -> WorkerRuntime:
    """Construct one worker graph without installing process globals yet."""
    services = build_runtime_services(settings)
    return WorkerRuntime(
        settings=settings,
        services=services,
        terminal_runtime=build_terminal_runtime(),
        dispatcher=build_worker_dispatcher_with_search(
            settings, services.tool_session_store
        ),
    )
