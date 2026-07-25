import ast
from pathlib import Path

_DOCUMENTED_NODE = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
_CLASS_ATTRIBUTE_NODE = ast.Assign | ast.AnnAssign


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _is_docstring_expr(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    names: list[str] = []

    def collect(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            names.append(target.id)
            return
        if isinstance(target, ast.Tuple | ast.List):
            for item in target.elts:
                collect(item)

    if isinstance(node, ast.Assign):
        for target in node.targets:
            collect(target)
    else:
        collect(node.target)

    return names


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _assignment_has_field_description(
    node: ast.Assign | ast.AnnAssign,
) -> bool:
    value = node.value
    if value is None or not isinstance(value, ast.Call):
        return False
    if _call_name(value.func) != "Field":
        return False
    return any(
        keyword.arg == "description"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
        and bool(keyword.value.value.strip())
        for keyword in value.keywords
    )


def _assignment_has_docstring(
    node: ast.Assign | ast.AnnAssign, next_node: ast.AST | None
) -> bool:
    return (next_node is not None and _is_docstring_expr(next_node)) or (
        _assignment_has_field_description(node)
    )


def _public_class_member_docstring_targets(
    node: ast.ClassDef, qualified_name: str
) -> list[str]:
    """Return public class members missing class, attribute, or function docs."""
    missing: list[str] = []

    for index, child in enumerate(node.body):
        if isinstance(child, _DOCUMENTED_NODE):
            if not _is_public(child.name):
                continue
            child_name = f"{qualified_name}.{child.name}"
            if ast.get_docstring(child) is None:
                missing.append(child_name)
            if isinstance(child, ast.ClassDef):
                missing.extend(
                    _public_class_member_docstring_targets(child, child_name)
                )
            continue

        if not isinstance(child, _CLASS_ATTRIBUTE_NODE):
            continue

        public_names = [
            name for name in _assignment_names(child) if _is_public(name)
        ]
        if not public_names:
            continue

        next_node = node.body[index + 1] if index + 1 < len(node.body) else None
        if not _assignment_has_docstring(child, next_node):
            missing.extend(f"{qualified_name}.{name}" for name in public_names)

    return missing


def _public_docstring_targets(path: Path) -> list[str]:
    """Return public module, class, function, and class-member targets missing docs."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing: list[str] = []
    if ast.get_docstring(tree) is None:
        missing.append(f"{path}: module")
    for node in tree.body:
        if not isinstance(node, _DOCUMENTED_NODE):
            continue
        if not _is_public(node.name):
            continue
        if ast.get_docstring(node) is None:
            missing.append(f"{path}: {node.name}")
        if isinstance(node, ast.ClassDef):
            missing.extend(
                f"{path}: {target}"
                for target in _public_class_member_docstring_targets(
                    node, node.name
                )
            )
    return missing


def test_public_docstring_targets_include_public_class_members(
    tmp_path: Path,
) -> None:
    """Protect class-level public attributes and nested members from regressions."""
    path = tmp_path / "sample.py"
    path.write_text(
        "\n".join(
            [
                '"""Module docs."""',
                "",
                "class PublicClass:",
                '    """Class docs."""',
                "",
                "    public_attr = 1",
                "    public_var: int",
                "    documented_attr = 1",
                '    """Attribute docs."""',
                '    documented_field: str = Field(description="Field docs.")',
                "",
                "    _private_attr = 1",
                "",
                "    def public_func(self) -> None:",
                "        pass",
                "",
                "    def _private_func(self) -> None:",
                "        pass",
                "",
                "    class PublicNested:",
                "        pass",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert _public_docstring_targets(path) == [
        f"{path}: PublicClass.public_attr",
        f"{path}: PublicClass.public_var",
        f"{path}: PublicClass.public_func",
        f"{path}: PublicClass.PublicNested",
    ]


def test_public_source_modules_keep_docstrings() -> None:
    """Keep public source modules, classes, functions, and class members documented."""
    module_paths = list(Path("src/local_shell_mcp").rglob("*.py"))

    missing = [
        target
        for path in module_paths
        if path.name != "__init__.py"
        for target in _public_docstring_targets(path)
    ]

    assert missing == []
