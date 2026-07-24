from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "local_shell_mcp"
_PACKAGE_NAME = "local_shell_mcp"
_ARCHITECTURE_DOC = Path(__file__).parents[1] / "docs" / "architecture.md"

# `main` is the process-composition entry point and may import executors. The
# REST executor consumes exactly one Human UI HTTP route-composition contract.
_ALLOWED_NON_SERVER_TO_SERVER_IMPORTS = frozenset()
_ALLOWED_HTTP_EXECUTOR_UI_IMPORTS = frozenset(
    {
        (
            "local_shell_mcp.executors.http.app",
            "local_shell_mcp.ui.http.routes",
        ),
    }
)
_ALLOWED_NON_EXECUTOR_TO_EXECUTOR_IMPORTS = frozenset(
    {
        ("local_shell_mcp.main", "local_shell_mcp.executors.http.app"),
        ("local_shell_mcp.main", "local_shell_mcp.executors.mcp.app"),
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
    assert not (_PACKAGE_ROOT / "server" / "mcp").exists()
    for name in ("app.py", "errors.py", "invocations.py", "tool_routes.py"):
        assert not (_PACKAGE_ROOT / "server" / "http" / name).exists()


def test_executor_imports_match_explicit_process_composition() -> None:
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if target.startswith(f"{_PACKAGE_NAME}.executors.")
        and not importer.startswith(f"{_PACKAGE_NAME}.executors.")
    )

    assert actual == _ALLOWED_NON_EXECUTOR_TO_EXECUTOR_IMPORTS


def test_mcp_executor_does_not_depend_on_transitional_server_or_ui() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.server.",
        f"{_PACKAGE_NAME}.ui.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.executors.mcp")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()


def test_http_executor_has_only_the_explicit_ui_route_dependency() -> None:
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.executors.http")
        and (
            target.startswith(f"{_PACKAGE_NAME}.server.")
            or target.startswith(f"{_PACKAGE_NAME}.ui.")
        )
    )

    assert actual == _ALLOWED_HTTP_EXECUTOR_UI_IMPORTS


def test_http_infrastructure_does_not_depend_on_executors_or_ui() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.server.",
        f"{_PACKAGE_NAME}.ui.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.http")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()
    assert not (_PACKAGE_ROOT / "server" / "shared").exists()


def test_telemetry_does_not_depend_on_ui_or_transport_adapters() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.http.",
        f"{_PACKAGE_NAME}.server.",
        f"{_PACKAGE_NAME}.ui.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.telemetry")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()


def test_ui_core_does_not_depend_on_executors_or_http_adapters() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.server.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.ui")
        and not importer.startswith(f"{_PACKAGE_NAME}.ui.http")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()
    for migrated_name in (
        "dashboard.py",
        "image_preview.py",
        "tui_runtime.py",
        "ui_security.py",
    ):
        assert not (_PACKAGE_ROOT / migrated_name).exists()


def test_ui_http_does_not_depend_on_executors_or_transitional_server() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.server.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.ui.http")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()
    residual = _PACKAGE_ROOT / "server" / "http"
    assert {path.name for path in residual.glob("*.py")} == {"__init__.py"}


def test_terminal_does_not_depend_on_transports_or_ui() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.http.",
        f"{_PACKAGE_NAME}.server.",
        f"{_PACKAGE_NAME}.ui.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.terminal")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()
    for migrated_name in ("conpty.py", "terminal_bridge.py", "tmux_helper.py"):
        assert not (_PACKAGE_ROOT / migrated_name).exists()


def test_audit_does_not_depend_on_delivery_or_terminal_layers() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.http.",
        f"{_PACKAGE_NAME}.server.",
        f"{_PACKAGE_NAME}.terminal.",
        f"{_PACKAGE_NAME}.ui.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.audit")
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()
    for migrated_name in ("audit.py", "audit_payloads.py"):
        assert not (_PACKAGE_ROOT / migrated_name).exists()


def test_patch_mechanics_stay_below_delivery_layers() -> None:
    forbidden_prefixes = (
        f"{_PACKAGE_NAME}.executors.",
        f"{_PACKAGE_NAME}.http.",
        f"{_PACKAGE_NAME}.server.",
        f"{_PACKAGE_NAME}.ui.",
    )
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer == f"{_PACKAGE_NAME}.ops.patch.envelope"
        and target.startswith(forbidden_prefixes)
    )

    assert actual == frozenset()
    assert not (_PACKAGE_ROOT / "patch_ops.py").exists()


def test_release_does_not_depend_on_runtime_layers() -> None:
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.release")
    )

    assert actual == frozenset()
    assert not (_PACKAGE_ROOT / "platform_wheel.py").exists()


def test_terminal_uses_only_explicit_low_level_ops_helpers() -> None:
    actual = frozenset(
        (importer, target)
        for importer, target in _local_imports()
        if importer.startswith(f"{_PACKAGE_NAME}.terminal")
        and target.startswith(f"{_PACKAGE_NAME}.ops.")
    )

    assert actual == frozenset(
        {
            (
                f"{_PACKAGE_NAME}.terminal.conpty",
                f"{_PACKAGE_NAME}.ops.utils.path",
            )
        }
    )


def _assert_ownership_map_covers(paths: set[str]) -> None:
    documentation = _ARCHITECTURE_DOC.read_text(encoding="utf-8")

    assert paths
    assert {path for path in paths if f"`{path}`" not in documentation} == set()


def test_patch_operation_ownership_map_is_documented() -> None:
    _assert_ownership_map_covers(
        {"ops/patch/__init__.py", "ops/patch/envelope.py"}
    )


def test_http_module_ownership_map_covers_every_file() -> None:
    _assert_ownership_map_covers(
        {f"http/{path.name}" for path in (_PACKAGE_ROOT / "http").glob("*.py")}
    )


def test_executor_ownership_map_covers_every_file() -> None:
    _assert_ownership_map_covers(
        {
            str(path.relative_to(_PACKAGE_ROOT)).replace("\\", "/")
            for path in (_PACKAGE_ROOT / "executors").rglob("*.py")
        }
    )


def test_owned_domain_maps_cover_every_file() -> None:
    for package in ("audit", "release", "telemetry", "terminal", "ui"):
        _assert_ownership_map_covers(
            {
                str(path.relative_to(_PACKAGE_ROOT)).replace("\\", "/")
                for path in (_PACKAGE_ROOT / package).rglob("*.py")
            }
        )


def test_dependency_cycles_match_explicit_architecture_debt() -> None:
    assert _dependency_cycles() == _ALLOWED_DEPENDENCY_CYCLES
