"""Typed input annotations for search and tree-view tools."""

from typing import Annotated

from pydantic import Field

TreeCwdArg = Annotated[
    str,
    Field(
        description="Directory path to render as a compact tree. Relative paths resolve inside the configured workspace."
    ),
]
SearchCwdArg = Annotated[
    str,
    Field(
        description="Directory path that narrows the search root. Relative paths resolve inside the configured workspace."
    ),
]
TreeDepthArg = Annotated[
    int,
    Field(
        description="Maximum directory nesting depth to include in the tree view."
    ),
]
TreeMaxEntriesArg = Annotated[
    int,
    Field(
        description="Maximum number of tree entries to return before reporting truncation. Bounded by server configuration."
    ),
]
GlobPatternArg = Annotated[
    str,
    Field(
        description="Glob expression matched against workspace-relative paths and file names."
    ),
]
GlobMaxResultsArg = Annotated[
    int,
    Field(
        description="Maximum number of matching paths to return. Bounded by server configuration."
    ),
]
GrepQueryArg = Annotated[
    str,
    Field(
        description="Text or regular expression pattern to search for; prefer built-in search tools so matches carry grounding metadata."
    ),
]
RegexArg = Annotated[
    bool,
    Field(description="Whether query is interpreted as a regular expression."),
]
CaseSensitiveArg = Annotated[
    bool,
    Field(description="Whether matching should be case-sensitive."),
]
GrepMaxResultsArg = Annotated[
    int | None,
    Field(
        description="Optional maximum number of matches to return. Omit to use the configured server limit."
    ),
]

SearchPathsArg = Annotated[
    str | list[str] | None,
    Field(
        description="Optional file, directory, glob, or list of them that scopes the high-level search; omit to search the workspace root."
    ),
]
