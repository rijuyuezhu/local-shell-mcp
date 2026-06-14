import pytest
from mcp.types import ToolAnnotations

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


def _sample_context():
    from local_shell_mcp.config.settings import Settings
    from local_shell_mcp.tools.contracts import McpToolContext

    return McpToolContext(
        settings=Settings(),
        read_only_tool=ToolAnnotations(readOnlyHint=True),
        connector_compatible_security_meta={
            "openai/toolInvocation/invoking": "Reading"
        },
        oauth_security_meta={"openai/toolInvocation/invoking": "Working"},
        ok=lambda data, message="": {
            "ok": True,
            "message": message,
            "data": data,
        },
        handled_error=lambda exc: {"ok": False, "message": str(exc)},
    )


async def _sample_tool() -> dict:
    return {}


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
        definition._mcp_security_meta(_sample_context())


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
