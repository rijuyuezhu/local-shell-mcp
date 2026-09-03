from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from fastapi import HTTPException
from mcp.types import ToolAnnotations

import local_shell_mcp.tools.declarative as declarative_module
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.oauth.core.context import (
    bind_oauth_claims,
    reset_oauth_claims,
)
from local_shell_mcp.tool_session import (
    SESSION_TERMINATION_PROMPT,
    SessionTerminationRequestedError,
    get_tool_session_store,
)
from local_shell_mcp.tools.declarative import ToolDefinition


@pytest.mark.asyncio
async def test_tool_definition_call_from_mapping_uses_defaults_and_filters_extra_args():
    async def sample_tool(required: str, optional: int = 3) -> dict:
        return {"required": required, "optional": optional}

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
    )

    assert await definition.call_from_mapping(
        {"required": "value", "ignored": "extra"}
    ) == {"required": "value", "optional": 3}
    assert await definition.call_from_mapping(
        {"required": "value", "optional": 9}
    ) == {"required": "value", "optional": 9}


@pytest.mark.asyncio
async def test_tool_definition_call_from_mapping_reports_missing_required_arg():
    async def sample_tool(required: str, optional: int = 3) -> dict:
        return {"required": required, "optional": optional}

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
    )

    with pytest.raises(ValueError, match="Missing required argument: required"):
        await definition.call_from_mapping({"optional": 9})


@pytest.mark.asyncio
async def test_tool_definition_call_from_mapping_ignores_varargs_and_kwargs():
    async def sample_tool(
        required: str,
        *args: str,
        keyword: int = 1,
        **kwargs: str,
    ) -> dict:
        return {
            "required": required,
            "args": args,
            "keyword": keyword,
            "kwargs": kwargs,
        }

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
    )

    assert await definition.call_from_mapping(
        {
            "required": "value",
            "args": ["not", "passed"],
            "keyword": 5,
            "unexpected": "not passed to **kwargs",
        }
    ) == {
        "required": "value",
        "args": (),
        "keyword": 5,
        "kwargs": {},
    }


@pytest.mark.asyncio
async def test_handler_owned_session_admission_skips_generic_wrapper(
    monkeypatch,
) -> None:
    admissions: list[dict[str, Any]] = []

    async def sample_tool(session_id: str) -> dict[str, str]:
        return {"session_id": session_id}

    monkeypatch.setattr(
        declarative_module,
        "enforce_tool_session_control",
        lambda args, **_kwargs: admissions.append(args),
    )
    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
        session_admission="handler",
    )

    assert await definition.call_from_mapping({"session_id": "SESSION01"}) == {
        "session_id": "SESSION01"
    }
    assert admissions == []

    mcp = _FakeMcp()
    definition.register_mcp(cast(Any, mcp), _sample_context())
    handler = cast(Callable[[str], Awaitable[dict[str, str]]], mcp.handler)
    assert await handler("SESSION02") == {"session_id": "SESSION02"}
    assert admissions == []


def _sample_context():
    from local_shell_mcp.config.settings import Settings
    from local_shell_mcp.tools.contracts import McpToolContext

    return McpToolContext(
        settings=Settings(),
        read_only_tool_annotations=ToolAnnotations(readOnlyHint=True),
    )


async def _sample_tool() -> dict:
    return {}


class _FakeMcp:
    def __init__(self) -> None:
        self.handler = None

    def tool(self, **kwargs):
        del kwargs

        def decorator(handler):
            self.handler = handler
            return handler

        return decorator


@pytest.mark.asyncio
async def test_mcp_handler_enforces_required_oauth_scopes():
    async def sample_tool() -> dict:
        return {"ok": True}

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
        oauth_scopes=("shell:read", "shell:execute"),
    )
    mcp = _FakeMcp()

    definition.register_mcp(cast(Any, mcp), _sample_context())
    assert mcp.handler is not None
    handler = cast(Callable[[], Awaitable[dict[str, bool]]], mcp.handler)

    claims_token = bind_oauth_claims({"scope": "shell:read"})
    try:
        with pytest.raises(HTTPException) as exc_info:
            await handler()
    finally:
        reset_oauth_claims(claims_token)
    assert exc_info.value.status_code == 403
    assert (
        exc_info.value.detail == "Missing required OAuth scope: shell:execute"
    )

    claims_token = bind_oauth_claims({"scope": "shell:read shell:execute"})
    try:
        assert await handler() == {"ok": True}
    finally:
        reset_oauth_claims(claims_token)


def test_tool_definition_rejects_unknown_mcp_security_profile():
    definition = ToolDefinition(
        func=_sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
        mcp_security_profile="future-profile",  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValueError, match="Invalid MCP security profile: future-profile"
    ):
        definition._mcp_security_meta()


def test_tool_definition_rejects_unknown_annotations():
    definition = ToolDefinition(
        func=_sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
        annotations="future-annotation",  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValueError, match="Invalid annotations: future-annotation"
    ):
        definition._mcp_annotations(_sample_context())


@pytest.mark.asyncio
async def test_http_style_tool_dispatch_stops_terminated_sessions(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    store.request_termination(session.session_id)
    called = False

    async def sample_tool(session_id: str) -> dict[str, str]:
        nonlocal called
        called = True
        return {"session_id": session_id}

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
    )

    with pytest.raises(SessionTerminationRequestedError) as exc_info:
        await definition.call_from_mapping({"session_id": session.session_id})
    assert not called
    assert SESSION_TERMINATION_PROMPT in str(exc_info.value)


@pytest.mark.asyncio
async def test_tool_dispatch_ignores_session_like_values_in_free_form_data(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    called = False

    async def sample_tool(
        session_id: str, env: dict[str, str]
    ) -> dict[str, object]:
        nonlocal called
        called = True
        return {"session_id": session_id, "env": env}

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
    )

    result = await definition.call_from_mapping(
        {
            "session_id": session.session_id,
            "env": {"session_id": "not-an-agent-session"},
        }
    )

    assert called
    assert result["env"] == {"session_id": "not-an-agent-session"}


@pytest.mark.asyncio
async def test_mcp_tool_dispatch_stops_terminated_sessions(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    store.request_termination(session.session_id)
    called = False

    async def sample_tool(session_id: str) -> dict[str, str]:
        nonlocal called
        called = True
        return {"session_id": session_id}

    definition = ToolDefinition(
        func=sample_tool,
        name="sample_tool",
        http_method="POST",
        http_path="/tools/sample_tool",
        oauth_scopes=("shell:read",),
        mcp_error_handler=lambda exc, _args, _kwargs: {"adapted": str(exc)},
    )
    mcp = _FakeMcp()
    definition.register_mcp(cast(Any, mcp), _sample_context())
    handler = cast(Callable[[str], Awaitable[dict[str, str]]], mcp.handler)
    claims_token = bind_oauth_claims({"scope": "shell:read"})
    try:
        with pytest.raises(SessionTerminationRequestedError) as exc_info:
            await handler(session.session_id)
    finally:
        reset_oauth_claims(claims_token)
    assert not called
    assert SESSION_TERMINATION_PROMPT in str(exc_info.value)
