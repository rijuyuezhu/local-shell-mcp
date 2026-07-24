from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "local_shell_mcp"
_PACKAGE_NAME = "local_shell_mcp"

# `main` is the process-composition entry point and may import transport adapters.
# The three metadata imports are known debt removed in the next hardening phase.
_ALLOWED_NON_SERVER_TO_SERVER_IMPORTS = frozenset(
    {
        (
            "local_shell_mcp.agent_bridge.tools",
            "local_shell_mcp.server.mcp.metadata",
        ),
        ("local_shell_mcp.main", "local_shell_mcp.server.http.app"),
        ("local_shell_mcp.main", "local_shell_mcp.server.mcp.app"),
        (
            "local_shell_mcp.tools.declarative",
            "local_shell_mcp.server.mcp.metadata",
        ),
        (
            "local_shell_mcp.tools.registry.agent",
            "local_shell_mcp.server.mcp.metadata",
        ),
    }
)

# Keep existing cycles visible and prevent new ones. Each set must shrink when the
# corresponding hardening phase extracts a dependency-leaf contract.
_ALLOWED_DEPENDENCY_CYCLES = frozenset(
    {
        frozenset(
            {
                "local_shell_mcp.agent_bridge.auth",
                "local_shell_mcp.agent_bridge.models",
                "local_shell_mcp.agent_bridge.skills",
                "local_shell_mcp.agent_bridge.sources",
            }
        ),
        frozenset(
            {
                "local_shell_mcp.ops.jobs",
                "local_shell_mcp.ops.shell",
            }
        ),
        frozenset(
            {
                "local_shell_mcp.remote_worker.cli",
                "local_shell_mcp.remote_worker.compat",
                "local_shell_mcp.remote_worker.worker",
            }
        ),
        frozenset(
            {
                "local_shell_mcp.remote_worker.lifecycle",
                "local_shell_mcp.remote_worker.runtime",
            }
        ),
    }
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(_PACKAGE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join((_PACKAGE_NAME, *parts))


def _resolve_import_from(
    importer: str,
    importer_path: Path,
    node: ast.ImportFrom,
) -> str | None:
    if node.level == 0:
        return node.module

    importer_parts = importer.split(".")
    package_parts = (
        importer_parts
        if importer_path.name == "__init__.py"
        else importer_parts[:-1]
    )
    parent_count = node.level - 1
    if parent_count > len(package_parts):
        return None

    resolved = package_parts[: len(package_parts) - parent_count]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _source_modules() -> dict[str, Path]:
    return {
        _module_name(path): path for path in sorted(_PACKAGE_ROOT.rglob("*.py"))
    }


def _local_imports() -> set[tuple[str, str]]:
    imports: set[tuple[str, str]] = set()
    for importer, path in _source_modules().items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import_from(importer, path, node)
                if target:
                    targets.append(target)
            for target in targets:
                if target.startswith(f"{_PACKAGE_NAME}."):
                    imports.add((importer, target))
    return imports


def _module_graph() -> dict[str, set[str]]:
    modules = _source_modules()
    graph: dict[str, set[str]] = defaultdict(set)
    for importer, target in _local_imports():
        candidate = target
        while candidate not in modules and "." in candidate:
            candidate = candidate.rsplit(".", 1)[0]
        if candidate in modules and candidate != importer:
            graph[importer].add(candidate)
    return graph


def _dependency_cycles() -> frozenset[frozenset[str]]:
    graph = _module_graph()
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    cycles: set[frozenset[str]] = set()

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        low_links[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)

        for dependency in graph.get(module, ()):
            if dependency not in indices:
                visit(dependency)
                low_links[module] = min(
                    low_links[module], low_links[dependency]
                )
            elif dependency in on_stack:
                low_links[module] = min(low_links[module], indices[dependency])

        if low_links[module] != indices[module]:
            return

        component: set[str] = set()
        while stack:
            dependency = stack.pop()
            on_stack.remove(dependency)
            component.add(dependency)
            if dependency == module:
                break
        if len(component) > 1:
            cycles.add(frozenset(component))

    for module in _source_modules():
        if module not in indices:
            visit(module)
    return frozenset(cycles)


def test_server_transport_imports_match_explicit_architecture_debt() -> None:
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if target.startswith(f"{_PACKAGE_NAME}.server.")
        and not importer.startswith(f"{_PACKAGE_NAME}.server.")
    )

    assert actual == _ALLOWED_NON_SERVER_TO_SERVER_IMPORTS


def test_dependency_cycles_match_explicit_architecture_debt() -> None:
    assert _dependency_cycles() == _ALLOWED_DEPENDENCY_CYCLES
