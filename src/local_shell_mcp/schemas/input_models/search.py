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
        description="Text or regular expression to search for, depending on the regex parameter."
    ),
]
GrepGlobArg = Annotated[
    str | None,
    Field(
        description="Optional ripgrep glob filter that restricts which files are searched."
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
        description="Optional path, glob, or list of paths/globs that scopes the high-level code search. Omit to search from cwd."
    ),
]
