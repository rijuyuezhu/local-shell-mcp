from typing import Any


def _mcp_content(response: Any, index: int = 0) -> Any:
    first = response[0]
    if isinstance(first, list):
        return first[index]
    return response[index]


def mcp_text(response: Any, index: int = 0) -> str:
    """Return text from a FastMCP call_tool response in tests."""
    return str(_mcp_content(response, index).text)


def nested_mcp_text(
    response: Any, index: int = 0, nested_index: int = 0
) -> str:
    """Return text from nested FastMCP responses produced by fetch tests."""
    content = _mcp_content(response, index)
    if isinstance(content, list):
        return str(content[nested_index].text)
    return str(content.text)


def mcp_structured(response: Any) -> dict[str, Any]:
    """Return structured content from a FastMCP structured-output response."""
    assert isinstance(response, tuple)
    assert isinstance(response[1], dict)
    return response[1]
