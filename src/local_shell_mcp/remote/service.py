"""Shared service helpers for remote-worker control and proxy calls."""

from __future__ import annotations

from typing import Any

from .manager import remote_manager


async def create_remote_invite(
    name: str | None, workdir: str | None, ttl_s: int | None
) -> dict[str, Any]:
    """Create a remote-worker invite through the process-wide manager."""
    return await remote_manager().create_invite(name, workdir, ttl_s)


def list_remote_machines() -> dict[str, Any]:
    """Return the remote machines currently known by the manager."""
    return remote_manager().list_machines()


def revoke_remote_machine(machine: str) -> dict[str, Any]:
    """Revoke and remove one remote machine by name."""
    return remote_manager().revoke(machine)


def rename_remote_machine(machine: str, new_name: str) -> dict[str, Any]:
    """Rename one remote machine by name."""
    return remote_manager().rename(machine, new_name)


async def call_remote_worker_tool(
    machine: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call a tool on a remote worker through the manager."""
    return await remote_manager().call(machine, tool, args, timeout_s)
