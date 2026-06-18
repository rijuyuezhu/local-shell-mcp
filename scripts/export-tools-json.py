#!/usr/bin/env python3
"""Export the current FastMCP tool definitions as JSON or Markdown."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.utils.serialization import to_jsonable

TOOL_GROUP_ORDER = (
    "Read-only connector tools",
    "Environment and safety",
    "Shell and Python",
    "Filesystem and search",
    "File download links",
    "Todo state",
    "Remote worker management",
    "Remote shell and Python",
    "Remote filesystem and search",
    "Remote file transfer",
    "Agent capability bridge",
    "Other tools",
)

ENVIRONMENT_TOOLS = {"environment_info", "secret_scan"}
SHELL_TOOLS = {
    "run_shell_command",
    "run_python_code",
    "start_persistent_shell",
    "send_persistent_shell_input",
    "read_persistent_shell_output",
    "kill_persistent_shell",
    "list_persistent_shells",
}
FILESYSTEM_TOOLS = {
    "list_files",
    "tree_view",
    "glob_search",
    "grep_search",
    "read_file",
    "read_many_files",
    "write_file",
    "edit_file",
    "multi_edit_file",
    "delete_file_or_dir",
    "apply_patch",
}
REMOTE_MANAGEMENT_TOOLS = {
    "remote_invite",
    "remote_list_machines",
    "remote_revoke_machine",
    "remote_rename_machine",
    "remote_environment_info",
}
REMOTE_SHELL_TOOLS = {
    "run_remote_shell_command",
    "run_remote_python_code",
    "start_remote_persistent_shell",
    "send_remote_persistent_shell_input",
    "read_remote_persistent_shell_output",
    "kill_remote_persistent_shell",
    "list_remote_persistent_shells",
}
REMOTE_FILESYSTEM_TOOLS = {
    "remote_list_files",
    "remote_tree_view",
    "remote_glob_search",
    "remote_grep_search",
    "remote_read_file",
    "remote_read_many_files",
    "remote_write_file",
    "remote_edit_file",
    "remote_multi_edit_file",
    "remote_delete_file_or_dir",
    "remote_apply_patch",
}
REMOTE_TRANSFER_TOOLS = {
    "remote_push_file",
    "remote_pull_file",
    "remote_copy_file",
    "remote_push_dir",
    "remote_pull_dir",
    "remote_copy_dir",
}


def _tool_to_jsonable_dict(tool: Any) -> dict[str, Any]:
    """Return a JSON-serializable representation of one MCP tool."""
    data = to_jsonable(tool, exclude_none=True)
    if isinstance(data, dict):
        return data
    if hasattr(tool, "dict"):
        return tool.dict(exclude_none=True)
    raise TypeError(f"Unsupported tool object type: {type(tool)!r}")


async def export_tools() -> list[dict[str, Any]]:
    """Build the MCP app and return the tools it exposes to clients."""
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-tools-") as tmp:
        tmp_root = Path(tmp)
        os.environ.setdefault(
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_root / "workspace")
        )
        os.environ.setdefault(
            "LOCAL_SHELL_MCP_STATE_DIR", str(tmp_root / "state")
        )
        clear_settings_cache()
        tools = await build_mcp().list_tools()
    return [_tool_to_jsonable_dict(tool) for tool in tools]


def _normalized_tools_payload(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the wrapped, stable JSON payload used by generated docs."""
    sorted_tools = sorted(tools, key=lambda tool: str(tool.get("name", "")))
    return {"count": len(sorted_tools), "tools": sorted_tools}


def _write_or_check_text(path: Path, text: str, *, check: bool) -> bool:
    """Write text or return whether an existing file already matches."""
    if check:
        return path.exists() and path.read_text() == text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def write_json(data: Any, output: Path | None, *, check: bool = False) -> bool:
    """Write JSON data to stdout or a file, or check a generated file."""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        if check:
            raise ValueError("--check requires --output for JSON output")
        sys.stdout.write(text)
        return True
    return _write_or_check_text(output, text, check=check)


def _markdown_escape(value: Any) -> str:
    """Escape a value for a compact Markdown table cell."""
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text.replace("|", "\\|")


def _schema_type(schema: dict[str, Any]) -> str:
    """Return a compact type label for a JSON schema fragment."""
    if "enum" in schema:
        return " / ".join(str(item) for item in schema["enum"])
    if schema_type := schema.get("type"):
        if isinstance(schema_type, list):
            return " / ".join(str(item) for item in schema_type)
        return str(schema_type)
    if any_of := schema.get("anyOf"):
        return " | ".join(
            _schema_type(item) for item in any_of if isinstance(item, dict)
        )
    if one_of := schema.get("oneOf"):
        return " | ".join(
            _schema_type(item) for item in one_of if isinstance(item, dict)
        )
    if "items" in schema:
        return "array"
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", maxsplit=1)[-1]
    return "object"


def _parameter_summary(tool: dict[str, Any]) -> str:
    """Return a compact required/optional parameter list for a tool."""
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if not properties:
        return "none"
    parts = []
    for name in sorted(properties):
        prop = properties[name]
        type_label = _schema_type(prop) if isinstance(prop, dict) else "value"
        status = "required" if name in required else "optional"
        parts.append(f"`{name}` ({type_label}, {status})")
    return "<br>".join(parts)


def _tool_group(name: str) -> str:
    """Return the documentation group for a generated tool name."""
    if name in {"search", "fetch"}:
        return "Read-only connector tools"
    if name in ENVIRONMENT_TOOLS:
        return "Environment and safety"
    if name in SHELL_TOOLS:
        return "Shell and Python"
    if name in FILESYSTEM_TOOLS:
        return "Filesystem and search"
    if name.endswith("_file_link") or name in {
        "create_file_link",
        "list_file_links",
        "revoke_file_link",
    }:
        return "File download links"
    if name in {"read_todos", "write_todos"}:
        return "Todo state"
    if name in REMOTE_MANAGEMENT_TOOLS:
        return "Remote worker management"
    if name in REMOTE_SHELL_TOOLS:
        return "Remote shell and Python"
    if name in REMOTE_FILESYSTEM_TOOLS:
        return "Remote filesystem and search"
    if name in REMOTE_TRANSFER_TOOLS:
        return "Remote file transfer"
    if (
        name.startswith("agent_")
        or name.startswith("list_agent_")
        or name
        in {
            "activate_agent_skill",
            "call_agent_mcp_tool",
        }
    ):
        return "Agent capability bridge"
    return "Other tools"


def render_tools_markdown(tools: list[dict[str, Any]]) -> str:
    """Render the tool reference Markdown page from exported tool schemas."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tool in sorted(tools, key=lambda item: str(item.get("name", ""))):
        groups[_tool_group(str(tool.get("name", "")))].append(tool)

    lines = [
        "# Tools reference",
        "",
        "<!-- Generated by scripts/export-tools-json.py. Do not edit by hand. -->",
        "",
        "This page is generated from the MCP app's live tool registry. Regenerate it when tool names, descriptions, input schemas, or availability rules change.",
        "",
        f"Generated tool count: **{len(tools)}**.",
        "",
        "The machine-readable schema is committed at [`generated/tools.json`](generated/tools.json).",
        "",
        "Tool availability still depends on client capability and server settings. Regular connector-style clients may only expose `search` and `fetch`; ChatGPT Developer Mode and full MCP clients can expose the complete MCP surface. Remote tools require remote workers to be enabled and connected. Agent bridge tools require agent bridge configuration.",
        "",
    ]
    for group in TOOL_GROUP_ORDER:
        grouped_tools = groups.get(group, [])
        if not grouped_tools:
            continue
        lines.extend(
            [
                f"## {group}",
                "",
                "| Tool | Parameters | Description |",
                "|---|---|---|",
            ]
        )
        for tool in grouped_tools:
            name = _markdown_escape(tool.get("name"))
            params = _parameter_summary(tool)
            desc = _markdown_escape(tool.get("description"))
            lines.append(f"| `{name}` | {params} | {desc} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def async_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write JSON to this file instead of stdout.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="Write a generated Markdown tools reference to this file.",
    )
    parser.add_argument(
        "--wrapped",
        action="store_true",
        help="Wrap the tool array in an object with a count field.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if requested generated outputs are stale.",
    )
    args = parser.parse_args()

    tools = await export_tools()
    payload: Any = _normalized_tools_payload(tools) if args.wrapped else tools
    ok = True
    if args.output is not None or args.markdown_output is None:
        ok &= write_json(payload, args.output, check=args.check)
    if args.markdown_output is not None:
        ok &= _write_or_check_text(
            args.markdown_output,
            render_tools_markdown(tools),
            check=args.check,
        )
    if not ok:
        print("generated tool reference is out of date", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
