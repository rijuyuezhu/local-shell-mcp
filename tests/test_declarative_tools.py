import pytest

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

    with pytest.raises(KeyError) as exc_info:
        await definition.call_from_mapping({"optional": 9})

    assert exc_info.value.args == ("required",)


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
