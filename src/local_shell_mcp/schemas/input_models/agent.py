"""Typed input annotations for agent bridge tools."""

from typing import Annotated, Any

from pydantic import Field

AgentSkillNameArg = Annotated[
    str, Field(description="Exact skill name returned by list_agent_skills.")
]
AgentServerArg = Annotated[
    str,
    Field(description="Exact configured agent MCP server name."),
]
AgentServerFilterArg = Annotated[
    str | None,
    Field(
        description="Optional exact agent MCP server name to filter listed tools."
    ),
]
AgentToolArg = Annotated[
    str,
    Field(
        description="Exact upstream tool name exposed by the selected agent MCP server."
    ),
]
AgentToolArgsArg = Annotated[
    dict[str, Any] | None,
    Field(
        description="JSON object of arguments passed to the upstream MCP tool."
    ),
]
