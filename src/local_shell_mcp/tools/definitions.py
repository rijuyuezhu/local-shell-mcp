"""Declarative static tool definitions shared by MCP and HTTP adapters."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, ClassVar, Literal, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..config.settings import Settings
from .base import HttpMethod, HttpToolRoute, McpToolContext, ToolRegistry

ToolMeta = Literal["protected", "connector"]
ToolAnnotation = Literal["read_only"]
ToolDescription = str | Callable[[McpToolContext], str]
ToolEnabled = Callable[[Settings], bool]
ToolFunc = Callable[..., Awaitable[Any]]


class LocalToolDecoratorFactory(Protocol):
    """Callable factory returned by a declarative registry for tool registration."""

    def __call__(
        self,
        *,
        http_method: HttpMethod | None,
        http_path: str | None,
        name: str | None = None,
        meta: ToolMeta = "protected",
        annotations: ToolAnnotation | None = None,
        description: ToolDescription | None = None,
        mcp_envelope: bool = True,
        enabled: ToolEnabled = ...,
    ) -> Callable[[ToolFunc], ToolDefinition]: ...


def _always_enabled(settings: Settings) -> bool:
    return True


def _tool_kwargs_from_mapping(
    signature: inspect.Signature, args: Mapping[str, Any]
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if name in args:
            kwargs[name] = args[name]
        elif parameter.default is inspect.Parameter.empty:
            raise KeyError(name)
    return kwargs


@dataclass(frozen=True)
class ToolDefinition:
    """Single static tool definition used to derive MCP and HTTP exposure."""

    func: ToolFunc
    name: str
    http_method: HttpMethod | None
    http_path: str | None
    meta: ToolMeta = "protected"
    annotations: ToolAnnotation | None = None
    description: ToolDescription | None = None
    mcp_envelope: bool = True
    enabled: ToolEnabled = _always_enabled

    @property
    def signature(self) -> inspect.Signature:
        """Return the typed public signature advertised to MCP clients."""
        return inspect.signature(self.func)

    def is_enabled(self, settings: Settings) -> bool:
        """Return whether this tool should be exposed for current settings."""
        return self.enabled(settings)

    def http_route(self) -> HttpToolRoute | None:
        """Return the HTTP route for this tool, if it has one."""
        if self.http_method is None or self.http_path is None:
            return None
        return HttpToolRoute(self.http_method, self.http_path, self.name)

    async def call_from_mapping(self, args: Mapping[str, Any]) -> Any:
        """Invoke the typed tool function from an HTTP-style argument mapping."""
        return await self.func(
            **_tool_kwargs_from_mapping(self.signature, args)
        )

    def http_handler(self) -> Callable[[dict[str, Any]], Awaitable[Any]]:
        """Return a local HTTP invocation handler for this tool."""

        async def handler(args: dict[str, Any]) -> Any:
            return await self.call_from_mapping(args)

        return handler

    def _mcp_meta(self, context: McpToolContext) -> dict[str, Any]:
        match self.meta:
            case "connector":
                return context.connector_meta
            case "protected":
                return context.protected_meta

    def _mcp_annotations(
        self, context: McpToolContext
    ) -> ToolAnnotations | None:
        match self.annotations:
            case "read_only":
                return context.read_only_tool
            case None:
                return None

    def _mcp_description(self, context: McpToolContext) -> str | None:
        if callable(self.description):
            return self.description(context)
        return self.description

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        """Register this tool on the provided FastMCP app."""

        @wraps(self.func)
        async def mcp_handler(*args: Any, **kwargs: Any) -> Any:
            try:
                result = await self.func(*args, **kwargs)
            except Exception as exc:
                return context.handled_error(exc)
            if not self.mcp_envelope:
                return result
            return context.ok(result, "")

        mcp_handler.__name__ = self.name
        mcp_handler.__qualname__ = self.name
        mcp_handler.__signature__ = self.signature  # type: ignore[attr-defined]
        mcp.tool(
            description=self._mcp_description(context),
            annotations=self._mcp_annotations(context),
            meta=self._mcp_meta(context),
            structured_output=False,
        )(mcp_handler)


class DeclarativeToolRegistry(ToolRegistry):
    """Registry base for static tools registered by local-tool decorators."""

    tools: ClassVar[tuple[ToolDefinition, ...]] = ()
    _context: McpToolContext | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Give every concrete registry its own tool collection."""
        super().__init_subclass__(**kwargs)
        cls.tools = ()

    @classmethod
    def register_tool(cls, tool: ToolDefinition) -> ToolDefinition:
        """Attach a tool definition to this registry class."""
        if any(existing.name == tool.name for existing in cls.tools):
            raise ValueError(f"Duplicate tool definition: {tool.name}")
        cls.tools = (*cls.tools, tool)
        return tool

    @classmethod
    def get_tool_decorator(cls) -> LocalToolDecoratorFactory:
        """Return a decorator factory that registers tools on this registry."""

        def registry_local_tool(
            *,
            http_method: HttpMethod | None,
            http_path: str | None,
            name: str | None = None,
            meta: ToolMeta = "protected",
            annotations: ToolAnnotation | None = None,
            description: ToolDescription | None = None,
            mcp_envelope: bool = True,
            enabled: ToolEnabled = _always_enabled,
        ) -> Callable[[ToolFunc], ToolDefinition]:
            def decorator(func: ToolFunc) -> ToolDefinition:
                return cls.register_tool(
                    ToolDefinition(
                        func=func,
                        name=name or func.__name__,
                        http_method=http_method,
                        http_path=http_path,
                        meta=meta,
                        annotations=annotations,
                        description=description,
                        mcp_envelope=mcp_envelope,
                        enabled=enabled,
                    )
                )

            return decorator

        return registry_local_tool

    def _enabled_tools(self) -> tuple[ToolDefinition, ...]:
        settings = self._settings()
        return tuple(tool for tool in self.tools if tool.is_enabled(settings))

    def _settings(self) -> Settings:
        if self._context is not None:
            return self._context.settings
        from ..config.settings import get_settings

        return get_settings()

    def http_routes(self) -> Iterable[HttpToolRoute]:
        return tuple(
            route
            for tool in self._enabled_tools()
            if (route := tool.http_route()) is not None
        )

    def http_handlers(
        self,
    ) -> Mapping[str, Callable[[dict[str, Any]], Awaitable[Any]]]:
        return {
            tool.name: tool.http_handler() for tool in self._enabled_tools()
        }

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        self._context = context
        try:
            for tool in self._enabled_tools():
                tool.register_mcp(mcp, context)
        finally:
            self._context = None


def local_tool(
    *,
    http_method: HttpMethod | None,
    http_path: str | None,
    name: str | None = None,
    meta: ToolMeta = "protected",
    annotations: ToolAnnotation | None = None,
    description: ToolDescription | None = None,
    mcp_envelope: bool = True,
    enabled: ToolEnabled = _always_enabled,
) -> Callable[[ToolFunc], ToolDefinition]:
    """Declare one static tool and derive MCP/HTTP adapters from it."""

    def decorator(func: ToolFunc) -> ToolDefinition:
        return ToolDefinition(
            func=func,
            name=name or func.__name__,
            http_method=http_method,
            http_path=http_path,
            meta=meta,
            annotations=annotations,
            description=description,
            mcp_envelope=mcp_envelope,
            enabled=enabled,
        )

    return decorator
