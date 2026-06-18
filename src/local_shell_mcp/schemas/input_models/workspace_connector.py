"""Typed input annotations for connector-compatible workspace tools."""

from typing import Annotated

from pydantic import Field

ConnectorSearchQueryArg = Annotated[
    str,
    Field(
        description="Case-insensitive literal text query used by connector-style workspace search."
    ),
]
ConnectorFetchIdArg = Annotated[
    str,
    Field(
        description="Workspace result id returned by connector-style search, normally a relative file path."
    ),
]
