"""ChatGPT connector-compatible read-only workspace search/fetch tools."""

from ...ops.workspace_connector import (
    fetch_error_output,
    fetch_execute,
    search_error_output,
    search_execute,
)
from ...schemas.input_models.workspace_connector import (
    ConnectorFetchIdArg,
    ConnectorSearchQueryArg,
)
from ...schemas.result_models.workspace_connector import (
    FetchOutput,
    SearchOutput,
)
from ..declarative import DeclarativeToolRegistry


class WorkspaceConnectorToolRegistry(DeclarativeToolRegistry):
    """Register the special read-only search/fetch surface for connector clients.

    These tools are intentionally separate from the richer coding-agent file and
    search tools. Regular ChatGPT custom connectors and Deep Research-style
    clients often expose only a document-source pattern: search for result cards,
    then fetch one result by id. They may not surface general-purpose tools such
    as code search, file reads, shell commands, edits, or remote-worker operations unless
    the client is in Developer Mode or otherwise supports the full MCP tool set.

    search/fetch therefore need three special MCP-facing choices:
    1. mcp_security_profile="connector_compatible" advertises a client-facing
       noauth-or-oauth securitySchemes profile for connector discovery. This is
       metadata only; AuthMiddleware still enforces real HTTP/MCP auth.
    2. annotations="read_only" marks the tools as non-mutating document-source
       operations.
    3. Their typed return models keep the connector-facing search/fetch
       payloads in the exact document-source shape expected by connector
       clients.
    """

    name = "workspace_connector"
    """Registry group name used for tool-surface organization."""


local_tool = WorkspaceConnectorToolRegistry.get_tool_decorator()


@local_tool(
    http_method="POST",
    http_path="/tools/workspace_search",
    mcp_security_profile="connector_compatible",
    annotations="read_only",
    mcp_error_handler=search_error_output,
)
async def workspace_search(query: ConnectorSearchQueryArg) -> SearchOutput:
    """Search workspace text files and return connector-compatible result cards. Use this sessionless read-only tool for connector-style document retrieval clients that expect a search -> fetch workflow: call workspace_search first, then pass a returned result id to fetch. This is a broad literal text search from the configured workspace root and returns at most one card per matched file. For coding-agent work inside an explicit session, prefer session-bound tree_view/glob_search for path discovery, search for content matches with grounding metadata, and read for precise file ranges."""
    return await search_execute(query)


@local_tool(
    http_method="POST",
    http_path="/tools/fetch",
    mcp_security_profile="connector_compatible",
    annotations="read_only",
    mcp_error_handler=fetch_error_output,
)
async def fetch(id: ConnectorFetchIdArg) -> FetchOutput:
    """Fetch one UTF-8 workspace text file as a connector-compatible document. The id should normally come from a prior workspace_search result card; fetch is the second step in the connector search -> fetch workflow. This tool is sessionless and read-only for connector clients. For coding-agent work that already has a session_id, prefer read(session_id, path) because it supports line selectors, numbered content, and edit-grounding snapshot metadata."""
    return await fetch_execute(id)
