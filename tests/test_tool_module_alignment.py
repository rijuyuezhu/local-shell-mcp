from pathlib import Path


def _module_names(path: str) -> set[str]:
    return {
        item.stem
        for item in Path(path).glob("*.py")
        if item.name != "__init__.py"
    }


def test_tool_family_modules_are_aligned() -> None:
    """Keep tool registry, operation, input schema, and output schema modules in sync."""
    registry = _module_names("src/local_shell_mcp/tools/registry")
    ops = _module_names("src/local_shell_mcp/ops")
    input_models = _module_names("src/local_shell_mcp/schemas/input_models")
    result_models = _module_names("src/local_shell_mcp/schemas/result_models")

    assert ops == registry
    assert input_models == registry
    assert result_models == registry


def test_operation_modules_do_not_use_ops_suffix() -> None:
    """Reserve ops module names for tool families and keep helpers under ops.utils."""
    operation_modules = _module_names("src/local_shell_mcp/ops")

    assert not any(name.endswith("_ops") for name in operation_modules)
    assert Path("src/local_shell_mcp/ops/utils/path.py").exists()
    assert Path("src/local_shell_mcp/ops/utils/temp_file.py").exists()
