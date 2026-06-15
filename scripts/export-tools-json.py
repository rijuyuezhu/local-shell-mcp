#!/usr/bin/env python3
"""Export the current FastMCP tool definitions as JSON."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp


def _jsonable_tool(tool: Any) -> dict[str, Any]:
    """Return a JSON-serializable representation of one MCP tool."""
    if hasattr(tool, "model_dump"):
        return tool.model_dump(mode="json", exclude_none=True)
    if hasattr(tool, "dict"):
        return tool.dict(exclude_none=True)
    raise TypeError(f"Unsupported tool object type: {type(tool)!r}")


async def export_tools() -> list[dict[str, Any]]:
    """Build the MCP app and return the tools it exposes to clients."""
    clear_settings_cache()
    tools = await build_mcp().list_tools()
    return [_jsonable_tool(tool) for tool in tools]


def write_json(data: Any, output: Path | None) -> None:
    """Write JSON data to stdout or a file."""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text)


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
    args = parser.parse_args()

    tools = await export_tools()
    payload: Any = (
        {"count": len(tools), "tools": tools} if args.wrapped else tools
    )
    write_json(payload, args.output)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
