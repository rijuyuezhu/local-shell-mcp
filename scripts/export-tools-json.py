#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any

from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


def _model_dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def export_tools() -> list[dict[str, Any]]:
    temp_workspace: tempfile.TemporaryDirectory[str] | None = None
    if "LOCAL_SHELL_MCP_WORKSPACE_ROOT" not in os.environ:
        temp_workspace = tempfile.TemporaryDirectory()
        os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] = temp_workspace.name
    try:
        get_settings.cache_clear()
        tools = await build_mcp().list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
                "outputSchema": tool.outputSchema,
                "annotations": _model_dump(tool.annotations),
                "meta": tool.meta,
            }
            for tool in sorted(tools, key=lambda item: item.name)
        ]
    finally:
        if temp_workspace is not None:
            temp_workspace.cleanup()


def main() -> None:
    print(json.dumps(asyncio.run(export_tools()), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
