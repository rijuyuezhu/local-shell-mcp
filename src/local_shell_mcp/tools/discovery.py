"""Runtime discovery for tool definition registries."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from functools import lru_cache

from .base import ToolRegistry

DEFINITION_PACKAGE = "local_shell_mcp.tools.registry"


@lru_cache(maxsize=1)
def discover_tool_registries() -> tuple[ToolRegistry, ...]:
    """Import built-in definition modules and instantiate their ToolRegistry subclasses."""
    package = importlib.import_module(DEFINITION_PACKAGE)
    registries: list[ToolRegistry] = []
    for module_info in pkgutil.iter_modules(
        package.__path__, f"{DEFINITION_PACKAGE}."
    ):
        module = importlib.import_module(module_info.name)
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate is ToolRegistry or not issubclass(
                candidate, ToolRegistry
            ):
                continue
            if candidate.__module__ != module.__name__:
                continue
            registries.append(candidate())
    registries.sort(
        key=lambda registry: registry.name or registry.__class__.__name__
    )
    return tuple(registries)


def get_primary_mcp_registry() -> ToolRegistry:
    """Return the registry that currently owns complete FastMCP construction."""
    owners = [
        registry for registry in discover_tool_registries() if registry.owns_mcp
    ]
    if len(owners) != 1:
        raise RuntimeError(
            f"Expected exactly one MCP registry, found {len(owners)}"
        )
    return owners[0]
