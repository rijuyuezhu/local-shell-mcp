"""ChatGPT connector-compatible read-only workspace search/fetch tools."""

from ...ops.workspace_connector_ops import fetch_execute, search_execute
from ..declarative import DeclarativeToolRegistry


class WorkspaceConnectorToolRegistry(DeclarativeToolRegistry):
    """Register the special read-only search/fetch surface for connector clients.

    These tools are intentionally separate from the richer coding-agent file and
    search tools. Regular ChatGPT custom connectors and Deep Research-style
    clients often expose only a document-source pattern: search for result cards,
    then fetch one result by id. They may not surface general-purpose tools such
    as grep_search, read_file, shell, patch, or remote-worker operations unless
    the client is in Developer Mode or otherwise supports the full MCP tool set.

    search/fetch therefore need three special MCP-facing choices:
    1. mcp_security_profile="connector_compatible" advertises a client-facing
       noauth-or-oauth securitySchemes profile for connector discovery. This is
       metadata only; AuthMiddleware still enforces real HTTP/MCP auth.
    2. annotations="read_only" marks the tools as non-mutating document-source
       operations.
    3. mcp_envelope=False keeps the connector-facing search/fetch payloads in
       the exact document-source shape expected by connector clients.
    """

    name = "workspace_connector"


local_tool = WorkspaceConnectorToolRegistry.get_tool_decorator()


@local_tool(
    http_method="POST",
    http_path="/tools/search",
    mcp_security_profile="connector_compatible",
    annotations="read_only",
    mcp_envelope=False,
)
async def search(query: str) -> str:
    """Search workspace text files and return connector-compatible result cards. Use this for connector-style document retrieval clients that expect a search -> fetch workflow. For code navigation or precise workspace inspection, use tools such as grep_search, glob_search, tree_view, read_file, or read_many_files. Parameter: query is a case-insensitive literal text query. The tool searches from the workspace root, returns at most one result card per matched file, and each card id is the value to pass to fetch."""
    return await search_execute(query)


@local_tool(
    http_method="POST",
    http_path="/tools/fetch",
    mcp_security_profile="connector_compatible",
    annotations="read_only",
    mcp_envelope=False,
)
async def fetch(id: str) -> str:
    """Fetch one workspace file as a connector-compatible document. Use this after search has returned a result id. For code navigation or precise workspace inspection, read_file provides line ranges, binary previews, and richer diagnostics. Parameter: id is the exact result id from search, normally a workspace-relative file path. The response contains id, title, text, url, and metadata fields. Binary files are represented by an omission message."""
    return await fetch_execute(id)
