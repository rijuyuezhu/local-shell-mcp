"""Declarative tool registration."""

import inspect
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, ClassVar, Literal, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..config.settings import Settings
from .contracts import (
    HttpMethod,
    HttpToolRoute,
    McpToolContext,
    ToolRegistry,
    ToolResult,
)

McpSecurityProfile = Literal["oauth", "connector_compatible"]
ToolAnnotation = Literal["read_only"]
ToolDescription = str | Callable[[McpToolContext], str]
ToolEnabled = Callable[[Settings], bool]
ToolFunc = Callable[..., Awaitable[Any]]
McpErrorHandler = Callable[[Exception, tuple[Any, ...], dict[str, Any]], Any]
_MCP_HANDLER_ENVELOPE_ATTR = "__local_shell_mcp_envelope__"
_MCP_HANDLER_ERROR_HANDLER_ATTR = "__local_shell_mcp_error_handler__"


def mark_mcp_handler_envelope(
    handler: Callable[..., Any], *, mcp_envelope: bool
) -> None:
    """Record whether an MCP handler returns the public ok/error envelope."""
    setattr(handler, _MCP_HANDLER_ENVELOPE_ATTR, mcp_envelope)


def mcp_handler_uses_envelope(handler: Callable[..., Any]) -> bool:
    """Return whether an MCP handler should return the public ok/error envelope."""
    return bool(getattr(handler, _MCP_HANDLER_ENVELOPE_ATTR, True))


def mark_mcp_handler_error_handler(
    handler: Callable[..., Any], error_handler: McpErrorHandler | None
) -> None:
    """Record an optional MCP handler error-to-result conversion strategy."""
    setattr(handler, _MCP_HANDLER_ERROR_HANDLER_ATTR, error_handler)


def mcp_handler_error_handler(
    handler: Callable[..., Any],
) -> McpErrorHandler | None:
    """Return the MCP error-to-result conversion strategy for a handler."""
    value = getattr(handler, _MCP_HANDLER_ERROR_HANDLER_ATTR, None)
    if value is None:
        return None
    return value


class LocalToolDecoratorFactory(Protocol):
    """Decorator factory for tool registration."""

    def __call__(
        self,
        *,
        http_method: HttpMethod | None,
        http_path: str | None,
        name: str | None = None,
        mcp_security_profile: McpSecurityProfile = "oauth",
        annotations: ToolAnnotation | None = None,
        description: ToolDescription | None = None,
        mcp_envelope: bool = True,
        mcp_error_handler: McpErrorHandler | None = None,
        enabled: ToolEnabled = ...,
    ) -> Callable[[ToolFunc], ToolDefinition]: ...


def _always_enabled(settings: Settings) -> bool:
    return True


def _normalize_description(text: str) -> str:
    """Return a clean MCP tool description from source text. This strips out any leading/trailing whitespace and normalizes paragraph spacing."""
    paragraphs = re.split(r"\n\s*\n", inspect.cleandoc(text))
    return "\n\n".join(
        " ".join(paragraph.split())
        for paragraph in paragraphs
        if paragraph.split()
    )


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
            raise ValueError(f"Missing required argument: {name}")
    return kwargs


@dataclass(frozen=True)
class ToolDefinition:
    """Tool definition used to derive MCP and HTTP exposure."""

    func: ToolFunc
    """Typed coroutine that implements the tool's canonical behavior."""
    name: str
    """Tool name exposed to MCP clients and HTTP dispatch."""
    http_method: HttpMethod | None
    """HTTP method for the REST adapter route, or None for MCP-only tools."""
    http_path: str | None
    """HTTP path for the REST adapter route, or None for MCP-only tools."""
    mcp_security_profile: McpSecurityProfile = "oauth"
    """Client-facing MCP securitySchemes profile advertised for this tool."""
    annotations: ToolAnnotation | None = None
    """MCP tool annotations applied during registration."""
    description: ToolDescription | None = None
    """Static or context-derived MCP description override. If not provided, the tool's docstring is used."""
    mcp_envelope: bool = True
    """Whether MCP calls should wrap results in the public ok/error envelope."""
    mcp_error_handler: McpErrorHandler | None = None
    """Optional MCP exception-to-result conversion used for tool errors and timeouts."""
    enabled: ToolEnabled = _always_enabled
    """Predicate controlling whether the tool is exposed for current settings."""

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
        """Return a HTTP invocation handler for this tool."""

        async def handler(args: dict[str, Any]) -> Any:
            return await self.call_from_mapping(args)

        return handler

    def _mcp_security_meta(self, context: McpToolContext) -> dict[str, Any]:
        match self.mcp_security_profile:
            case "connector_compatible":
                return context.connector_compatible_security_meta
            case "oauth":
                return context.oauth_security_meta
            case _:
                raise ValueError(
                    f"Invalid MCP security profile: {self.mcp_security_profile}"
                )

    def _mcp_annotations(
        self, context: McpToolContext
    ) -> ToolAnnotations | None:
        match self.annotations:
            case "read_only":
                return context.read_only_tool
            case None:
                return None
            case _:
                raise ValueError(f"Invalid annotations: {self.annotations}")

    def _mcp_description(self, context: McpToolContext) -> str | None:
        if callable(self.description):
            description = self.description(context)
        elif self.description is not None:
            description = self.description
        else:
            description = self.func.__doc__ or ""
        normalized = _normalize_description(description)
        return normalized or None

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        """Register this tool on the provided FastMCP app."""

        @wraps(self.func)
        async def mcp_handler(*args: Any, **kwargs: Any) -> Any:
            try:
                result = await self.func(*args, **kwargs)
            except Exception as exc:
                if self.mcp_error_handler is not None:
                    return self.mcp_error_handler(exc, args, kwargs)

                # If no error handler is configured:
                # 1. Raise the exception as-is if mcp_envelope is False
                # 2. Return a handled error envelope if mcp_envelope is True
                if not self.mcp_envelope:
                    raise
                return context.handled_error(exc)

            if not self.mcp_envelope:
                return result
            return context.ok(result, "")

        mcp_handler.__name__ = self.name
        mcp_handler.__qualname__ = self.name
        mark_mcp_handler_envelope(mcp_handler, mcp_envelope=self.mcp_envelope)
        mark_mcp_handler_error_handler(mcp_handler, self.mcp_error_handler)
        if self.mcp_envelope:
            signature = self.signature.replace(return_annotation=ToolResult)
            mcp_handler.__signature__ = signature  # type: ignore[attr-defined]
            mcp_handler.__annotations__["return"] = ToolResult
        else:
            mcp_handler.__signature__ = self.signature  # type: ignore[attr-defined]
        mcp.tool(
            description=self._mcp_description(context),
            annotations=self._mcp_annotations(context),
            meta=self._mcp_security_meta(context),
            structured_output=True,
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
            mcp_security_profile: McpSecurityProfile = "oauth",
            annotations: ToolAnnotation | None = None,
            description: ToolDescription | None = None,
            mcp_envelope: bool = True,
            mcp_error_handler: McpErrorHandler | None = None,
            enabled: ToolEnabled = _always_enabled,
        ) -> Callable[[ToolFunc], ToolDefinition]:
            def decorator(func: ToolFunc) -> ToolDefinition:
                return cls.register_tool(
                    ToolDefinition(
                        func=func,
                        name=name or func.__name__,
                        http_method=http_method,
                        http_path=http_path,
                        mcp_security_profile=mcp_security_profile,
                        annotations=annotations,
                        description=description,
                        mcp_envelope=mcp_envelope,
                        mcp_error_handler=mcp_error_handler,
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
