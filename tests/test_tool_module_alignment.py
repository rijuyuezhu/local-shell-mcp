from pathlib import Path

_NON_REGISTRY_OPERATION_MODULES = {"bash", "files_service"}


def _module_names(
    path: str, *, include_family_packages: bool = False
) -> set[str]:
    root = Path(path)
    names = {
        item.stem for item in root.glob("*.py") if item.name != "__init__.py"
    }
    if include_family_packages:
        names.update(
            item.name
            for item in root.iterdir()
            if item.is_dir()
            and item.name != "utils"
            and (item / "__init__.py").is_file()
        )
    return names


def _owned_family_names(
    shared_path: str,
    tool_owned_path: str,
    *,
    include_family_packages: bool = False,
) -> set[str]:
    """Return one family set while rejecting duplicate physical owners."""
    shared = _module_names(
        shared_path, include_family_packages=include_family_packages
    )
    tool_owned = _module_names(
        tool_owned_path, include_family_packages=include_family_packages
    )
    assert shared.isdisjoint(tool_owned)
    return shared | tool_owned


def test_tool_family_modules_are_aligned() -> None:
    """Keep tool registry, operation, input schema, and output schema modules in sync."""
    registry = _module_names("src/local_shell_mcp/tools/registry")
    ops = _owned_family_names(
        "src/local_shell_mcp/ops",
        "src/local_shell_mcp/tools/ops",
        include_family_packages=True,
    )
    input_models = _owned_family_names(
        "src/local_shell_mcp/schemas/input_models",
        "src/local_shell_mcp/tools/schemas/input_models",
    )
    result_models = _owned_family_names(
        "src/local_shell_mcp/schemas/result_models",
        "src/local_shell_mcp/tools/schemas/result_models",
    )

    assert ops - _NON_REGISTRY_OPERATION_MODULES == registry
    assert ops >= _NON_REGISTRY_OPERATION_MODULES
    assert input_models == registry
    assert result_models == registry


def test_operation_modules_do_not_use_ops_suffix() -> None:
    """Reserve ops module names for tool families and keep helpers under ops.utils."""
    operation_modules = _owned_family_names(
        "src/local_shell_mcp/ops",
        "src/local_shell_mcp/tools/ops",
        include_family_packages=True,
    )

    assert not any(name.endswith("_ops") for name in operation_modules)
    assert Path("src/local_shell_mcp/ops/utils/path.py").exists()
    assert Path("src/local_shell_mcp/ops/utils/temp_file.py").exists()
