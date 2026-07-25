"""Normalize upstream MCP protocol objects and manage client sessions for configured agent bridge servers."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

from ..utils.serialization import to_jsonable
from .auth import (
    OAuthProviderFactory,
    build_stored_oauth_provider,
    oauth_status,
    resolve_config_mapping,
)
from .auth_store import AgentAuthStore
from .models import AgentMcpServerConfig


@dataclass(frozen=True)
class AgentMcpTool:
    """Normalized description of an upstream MCP tool exposed through the bridge."""

    name: str
    """Upstream MCP tool name."""
    description: str
    """Human-readable tool description advertised by the upstream server."""
    input_schema: dict[str, Any]
    """JSON schema describing the upstream tool input payload."""


def _value(source: Any, name: str, default: Any = None) -> Any:
    """Read an MCP protocol field from either a mapping or SDK object."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def normalize_mcp_tool(tool: Any) -> AgentMcpTool:
    """Normalize SDK-specific MCP tool objects into a stable serializable shape."""
    input_schema = _value(tool, "inputSchema")
    if input_schema is None:
        input_schema = _value(tool, "input_schema", {})

    return AgentMcpTool(
        name=str(_value(tool, "name", "")),
        description=str(_value(tool, "description", "") or ""),
        input_schema=input_schema,
    )


def _normalize_content_item(item: Any) -> Any:
    """Convert MCP content blocks to JSON-serializable dictionaries while preserving unknown fields."""
    if _value(item, "type") == "text":
        return {"type": "text", "text": _value(item, "text", "")}
    jsonable_item = to_jsonable(item)
    if isinstance(jsonable_item, dict):
        return jsonable_item
    return {"type": "repr", "repr": repr(item)}


def normalize_tool_result(result: Any) -> dict[str, Any]:
    """Convert an MCP tool result into a stable payload with content blocks and error state."""
    structured_content = _value(result, "structuredContent")
    if structured_content is None:
        structured_content = _value(result, "structured_content")
    structured_content = to_jsonable(structured_content)

    return {
        "is_error": bool(
            _value(result, "isError", False)
            or _value(result, "is_error", False)
        ),
        "content": [
            _normalize_content_item(item)
            for item in _value(result, "content", [])
        ],
        "structured_content": structured_content,
    }


class AgentMcpClientManager:
    """Create short-lived MCP client sessions for stdio, HTTP, and SSE upstream servers."""

    def __init__(
        self,
        call_timeout_s: float = 60,
        auth_store: AgentAuthStore | None = None,
        oauth_provider_factory: OAuthProviderFactory | None = None,
    ) -> None:
        self.call_timeout_s = call_timeout_s
        self.auth_store = auth_store
        self.oauth_provider_factory = oauth_provider_factory

    def resolved_maps(
        self, name: str, server: AgentMcpServerConfig
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Resolve transport env/headers immediately before opening a connection."""
        return (
            resolve_config_mapping(self.auth_store, name, server.env),
            resolve_config_mapping(self.auth_store, name, server.headers),
        )

    def redaction_maps(
        self, name: str, server: AgentMcpServerConfig
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Resolve configured values solely for error/payload redaction."""
        return self.resolved_maps(name, server)

    def auth_status(
        self, name: str, server: AgentMcpServerConfig
    ) -> dict[str, Any]:
        """Return public authorization status for registry payloads."""
        return oauth_status(self.auth_store, name, server)

    def _oauth_auth(
        self, name: str, server: AgentMcpServerConfig
    ) -> httpx.Auth | None:
        if server.auth.mode != "oauth":
            return None
        if self.oauth_provider_factory is not None:
            return self.oauth_provider_factory(name, server)
        if self.auth_store is None:
            raise ValueError(
                f"OAuth authorization required for {name}; run local-shell-mcp mcp auth {name}"
            )
        status = self.auth_status(name, server)
        if not status["authorized"]:
            raise ValueError(
                f"OAuth authorization required for {name}; run local-shell-mcp mcp auth {name}"
            )
        return build_stored_oauth_provider(self.auth_store, name, server)

    @asynccontextmanager
    async def _session(
        self, name: str, server: AgentMcpServerConfig
    ) -> AsyncGenerator[ClientSession]:
        """Open and initialize the transport-specific MCP client session for one configured server."""
        env, headers = self.resolved_maps(name, server)
        auth = self._oauth_auth(name, server)
        match server.type:
            case "stdio":
                if not server.command:
                    raise ValueError("stdio MCP server requires command")
                params = StdioServerParameters(
                    command=server.command,
                    args=server.args,
                    env=env or None,
                )
                async with (
                    stdio_client(params) as (read_stream, write_stream),
                    ClientSession(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    yield session
            case "http":
                if not server.url:
                    raise ValueError("http MCP server requires url")
                async with (
                    httpx.AsyncClient(
                        headers=headers or None, auth=auth
                    ) as client,
                    streamable_http_client(server.url, http_client=client) as (
                        read_stream,
                        write_stream,
                        _get_session_id,
                    ),
                    ClientSession(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    yield session
            case "sse":
                if not server.url:
                    raise ValueError("sse MCP server requires url")
                async with (
                    sse_client(
                        server.url, headers=headers or None, auth=auth
                    ) as (
                        read_stream,
                        write_stream,
                    ),
                    ClientSession(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    yield session
            case _:
                raise ValueError(
                    f"unsupported MCP server type for {name}: {server.type}"
                )

    async def list_tools(
        self, name: str, server: AgentMcpServerConfig
    ) -> list[AgentMcpTool]:
        """Page through an upstream server's tool list within the configured call timeout."""

        async def _list_tools() -> list[AgentMcpTool]:
            async with self._session(name, server) as session:
                tools: list[AgentMcpTool] = []
                cursor: str | None = None
                while True:
                    result = await session.list_tools(
                        params=PaginatedRequestParams(cursor=cursor)
                    )
                    tools.extend(
                        normalize_mcp_tool(tool)
                        for tool in _value(result, "tools", result)
                    )
                    cursor = getattr(result, "nextCursor", None)
                    if not cursor:
                        return tools

        return await asyncio.wait_for(
            _list_tools(), timeout=self.call_timeout_s
        )

    async def call_tool(
        self,
        name: str,
        server: AgentMcpServerConfig,
        tool: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke an upstream MCP tool and normalize its protocol result for local-shell-mcp responses."""

        async def _call_tool() -> dict[str, Any]:
            async with self._session(name, server) as session:
                return normalize_tool_result(
                    await session.call_tool(tool, args)
                )

        return await asyncio.wait_for(_call_tool(), timeout=self.call_timeout_s)
