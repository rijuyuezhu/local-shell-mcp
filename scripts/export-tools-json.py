#!/usr/bin/env python3
"""Export the current FastMCP tool definitions as JSON."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.utils.serialization import to_jsonable


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


def _wrapped_payload(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a stable wrapped JSON payload."""
    return {
        "count": len(tools),
        "tools": sorted(tools, key=lambda tool: str(tool.get("name", ""))),
    }


def write_json(data: Any, output: Path | None, *, check: bool) -> bool:
    """Write JSON data to stdout or a file, or check that a file is current."""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        if check:
            raise ValueError("--check requires --output")
        sys.stdout.write(text)
        return True
    if check:
        return output.exists() and output.read_text() == text
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return True


async def async_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write JSON to this file instead of stdout.",
    )
    parser.add_argument(
        "--wrapped",
        action="store_true",
        help="Wrap the tool array in an object with a count field.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated JSON file is stale.",
    )
    args = parser.parse_args()

    tools = await export_tools()
    payload: Any = _wrapped_payload(tools) if args.wrapped else tools
    if not write_json(payload, args.output, check=args.check):
        print("generated tools JSON is out of date", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
