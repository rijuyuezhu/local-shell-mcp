"""Shared input annotations for remote-worker tools."""

from typing import Annotated, Any, Literal

from pydantic import Field

RemoteMachineArg = Annotated[
    str,
    Field(
        description="Exact remote worker machine name returned by remote_list_machines."
    ),
]
RemoteSourceMachineArg = Annotated[
    str,
    Field(
        description="Exact source remote worker machine name returned by remote_list_machines."
    ),
]
RemoteDestinationMachineArg = Annotated[
    str,
    Field(
        description="Exact destination remote worker machine name returned by remote_list_machines."
    ),
]
RemoteNewNameArg = Annotated[
    str,
    Field(
        description="New stable remote worker machine name to use for later remote calls."
    ),
]
RemoteInviteNameArg = Annotated[
    str | None,
    Field(
        description="Optional friendly remote worker name bound to the invite."
    ),
]
RemoteWorkdirArg = Annotated[
    str | None,
    Field(
        description="Optional worker-side starting directory requested by the invite."
    ),
]
RemoteInviteTtlArg = Annotated[
    int | None,
    Field(
        description="Optional invite lifetime in seconds, clamped by remote invite limits."
    ),
]
RemotePathArg = Annotated[
    str,
    Field(description="Path on the selected remote worker machine."),
]
RemoteSourcePathArg = Annotated[
    str,
    Field(description="Source path on the source remote worker machine."),
]
RemoteDestinationPathArg = Annotated[
    str,
    Field(
        description="Destination path on the destination remote worker machine."
    ),
]
LocalPathArg = Annotated[
    str,
    Field(description="Workspace-relative path on the control server."),
]
RemoteOverwriteArg = Annotated[
    bool,
    Field(
        description="Whether to replace an existing destination file or directory."
    ),
]
RemoteChunkSizeArg = Annotated[
    int | None,
    Field(
        description="Optional transfer chunk size in bytes. Omit to use the configured default."
    ),
]
RemoteTimeoutArg = Annotated[
    int | None,
    Field(
        description="Optional remote job timeout in seconds for this worker call."
    ),
]
RemoteCommandArg = Annotated[
    str,
    Field(
        description="Shell command string to execute on the selected remote worker."
    ),
]
RemotePythonCodeArg = Annotated[
    str,
    Field(
        description="Python source code to execute on the selected remote worker."
    ),
]
RemoteCwdArg = Annotated[
    str,
    Field(description="Working directory on the selected remote worker."),
]
RemoteSessionIdArg = Annotated[
    str,
    Field(
        description="Persistent shell session identifier on the selected remote worker."
    ),
]
RemoteInputTextArg = Annotated[
    str,
    Field(description="Text to send to the remote persistent shell session."),
]
RemoteEnterArg = Annotated[
    bool,
    Field(
        description="Whether to append Enter after sending remote shell input."
    ),
]
RemoteLinesArg = Annotated[
    int,
    Field(
        description="Number of recent terminal lines to read from the remote persistent shell."
    ),
]
RemoteDepthArg = Annotated[
    int,
    Field(description="Maximum directory depth for the remote tree view."),
]
RemoteMaxEntriesArg = Annotated[
    int,
    Field(description="Maximum number of remote tree/list entries to return."),
]
RemotePatternArg = Annotated[
    str,
    Field(description="Pattern used for remote glob search."),
]
RemoteQueryArg = Annotated[
    str,
    Field(
        description="Text or regular expression used for remote content search."
    ),
]
RemoteGlobArg = Annotated[
    str | None,
    Field(description="Optional glob filter for remote content search."),
]
RemoteRegexArg = Annotated[
    bool,
    Field(
        description="Whether the remote search query is interpreted as a regular expression."
    ),
]
RemoteCaseSensitiveArg = Annotated[
    bool,
    Field(
        description="Whether remote content search should be case-sensitive."
    ),
]
RemoteMaxResultsArg = Annotated[
    int | None,
    Field(
        description="Optional maximum number of remote search results to return."
    ),
]
RemoteContentArg = Annotated[
    str,
    Field(
        description="Complete text content to write on the selected remote worker."
    ),
]
RemoteOldTextArg = Annotated[
    str,
    Field(description="Exact existing remote file text to replace."),
]
RemoteNewTextArg = Annotated[
    str,
    Field(description="Replacement text for a remote exact-text edit."),
]
RemoteReplaceAllArg = Annotated[
    bool,
    Field(description="Whether to replace every exact remote text occurrence."),
]
RemoteEditsArg = Annotated[
    list[dict],
    Field(description="Ordered exact-text edits to apply to one remote file."),
]
RemoteRecursiveArg = Annotated[
    bool,
    Field(
        description="Whether remote deletion may recurse into non-empty directories."
    ),
]
RemotePatchArg = Annotated[
    str,
    Field(
        description="Unified diff text to apply on the selected remote worker."
    ),
]

RemoteFacadeOpArg = Annotated[
    Literal[
        "environment",
        "read",
        "search",
        "edit_lines",
        "bash",
        "python",
        "list_files",
        "tree",
        "glob",
        "grep",
        "write_file",
        "apply_patch",
        "delete",
        "job_start",
        "job_list",
        "job_tail",
        "job_stop",
        "job_retry",
    ],
    Field(
        description="High-level remote operation to run on the selected worker."
    ),
]
RemoteFacadeArgsArg = Annotated[
    dict[str, Any],
    Field(
        description="Operation-specific arguments forwarded to the remote worker. Do not include machine."
    ),
]
