"""MCP tool registration for remote-worker proxy tools."""

import inspect
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, TypeAdapter

from ...ops.remote import remote_execute
from ...remote.service import (
    call_remote_worker_tool,
    create_remote_invite,
    list_remote_machines,
    rename_remote_machine,
    revoke_remote_machine,
)
from ...remote.transfer import (
    copy_local_dir_to_remote,
    copy_local_file_to_remote,
    copy_remote_dir_to_local,
    copy_remote_dir_to_remote,
    copy_remote_file_to_local,
    copy_remote_file_to_remote,
)
from ...schemas.input_models.files import ReadFilesArg
from ...schemas.input_models.jobs import (
    IncludeFinishedArg,
    JobCommandArg,
    JobCwdArg,
    JobIdArg,
    JobNameArg,
    JobTailLinesArg,
)
from ...schemas.input_models.remote import (
    LocalPathArg,
    RemoteCaseSensitiveArg,
    RemoteChunkSizeArg,
    RemoteCommandArg,
    RemoteContentArg,
    RemoteCwdArg,
    RemoteDepthArg,
    RemoteDestinationMachineArg,
    RemoteDestinationPathArg,
    RemoteEditsArg,
    RemoteEnterArg,
    RemoteFacadeArgsArg,
    RemoteFacadeOpArg,
    RemoteGlobArg,
    RemoteInputTextArg,
    RemoteInviteNameArg,
    RemoteInviteTtlArg,
    RemoteLinesArg,
    RemoteMachineArg,
    RemoteMaxEntriesArg,
    RemoteMaxResultsArg,
    RemoteNewNameArg,
    RemoteNewTextArg,
    RemoteOldTextArg,
    RemoteOverwriteArg,
    RemotePatchArg,
    RemotePathArg,
    RemotePatternArg,
    RemotePythonCodeArg,
    RemoteQueryArg,
    RemoteRecursiveArg,
    RemoteRegexArg,
    RemoteReplaceAllArg,
    RemoteSessionIdArg,
    RemoteSourceMachineArg,
    RemoteSourcePathArg,
    RemoteTimeoutArg,
    RemoteWorkdirArg,
)
from ...schemas.input_models.shell import ToolExplanationArg, ToolPurposeArg
from ...schemas.result_models.environment import EnvironmentInfoOutput
from ...schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditFileOutput,
    ListFilesOutput,
    MultiEditFileOutput,
    ReadFileOutput,
    ReadManyFilesOutput,
    WriteFileOutput,
)
from ...schemas.result_models.jobs import (
    JobListOutput,
    JobRetryOutput,
    JobStartOutput,
    JobStopOutput,
    JobTailOutput,
)
from ...schemas.result_models.patch import ApplyPatchOutput
from ...schemas.result_models.remote import (
    RemoteCopyDirOutput,
    RemoteCopyFileOutput,
    RemoteFacadeOutput,
    RemoteInviteOutput,
    RemoteListMachinesOutput,
    RemoteRenameMachineOutput,
    RemoteRevokeMachineOutput,
)
from ...schemas.result_models.search import (
    GlobSearchOutput,
    GrepSearchOutput,
    TreeViewOutput,
)
from ...schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    RunPythonCodeOutput,
    RunShellCommandOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)
from ...tools.contracts import McpToolContext
from ...utils.serialization import to_jsonable


def _description(text: str) -> str:
    """Return a clean MCP tool description from source text."""
    paragraphs = re.split(r"\n\s*\n", inspect.cleandoc(text))
    return "\n\n".join(
        " ".join(paragraph.split())
        for paragraph in paragraphs
        if paragraph.split()
    )


def _remote_data(result: dict[str, Any]) -> dict[str, Any]:
    """Extract a worker data payload or raise a tool execution error."""
    if result.get("ok", False):
        data = to_jsonable(result.get("data"))
        if isinstance(data, dict):
            if data.get("ok") is False or data.get("status") == "error":
                message = (
                    data.get("message")
                    or data.get("error")
                    or data.get("error_type")
                    or "remote worker tool failed"
                )
                raise RuntimeError(str(message))
            return data
        return {"result": data}
    message = (
        result.get("message") or result.get("error") or "remote job failed"
    )
    raise RuntimeError(str(message))


async def _remote_call(
    machine: RemoteMachineArg,
    tool: str,
    args: dict[str, Any],
    timeout_s: RemoteTimeoutArg = None,
) -> dict[str, Any]:
    """Call a worker-side tool and return its structured data payload."""
    return _remote_data(
        await call_remote_worker_tool(machine, tool, args, timeout_s)
    )


async def _remote_typed[TModel: BaseModel](
    model: type[TModel],
    machine: RemoteMachineArg,
    tool: str,
    args: dict[str, Any],
    timeout_s: RemoteTimeoutArg = None,
) -> TModel:
    """Call a remote worker tool and validate its data payload."""
    return model.model_validate(
        await _remote_call(machine, tool, args, timeout_s)
    )


def register_remote_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    settings = context.settings
    remote_meta = context.scoped_oauth_security_meta(("remote:use",))
    remote_read_meta = context.scoped_oauth_security_meta(
        ("remote:use", "shell:read")
    )
    remote_write_meta = context.scoped_oauth_security_meta(
        ("remote:use", "shell:read", "shell:write")
    )
    remote_execute_meta = context.scoped_oauth_security_meta(
        ("remote:use", "shell:read", "shell:execute")
    )
    remote_patch_meta = context.scoped_oauth_security_meta(
        ("remote:use", "shell:read", "shell:write", "git:write")
    )
    remote_facade_meta = context.scoped_oauth_security_meta(
        (
            "remote:use",
            "shell:read",
            "shell:write",
            "shell:execute",
            "git:write",
        )
    )

    @mcp.tool(
        structured_output=True,
        meta=remote_meta,
        description=_description(
            f"""Create a one-time command for a remote machine to join this control server. Use when you need to run workspace tools on another worker. Defaults: ttl_s defaults to the configured remote_invite_ttl_s={settings.remote_invite_ttl_s} seconds when omitted. Security: treat the invite as sensitive because it grants enrollment capability."""
        ),
    )
    async def remote_invite(
        name: RemoteInviteNameArg = None,
        workdir: RemoteWorkdirArg = None,
        ttl_s: RemoteInviteTtlArg = None,
    ) -> RemoteInviteOutput:
        """Create a one-time remote-worker invite."""
        return await create_remote_invite(name, workdir, ttl_s)

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_list_machines() -> RemoteListMachinesOutput:
        """List remote worker machines currently known to the control server. Use before running any remote_* tool when you need the machine name or want to verify that a worker is connected."""
        return list_remote_machines()

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_revoke_machine(
        machine: RemoteMachineArg,
    ) -> RemoteRevokeMachineOutput:
        """Revoke and remove a remote worker machine. Use when a worker should no longer receive jobs or has become stale/untrusted. This is a control-plane action and cannot be undone except by re-inviting the worker."""
        return revoke_remote_machine(machine)

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_rename_machine(
        machine: RemoteMachineArg, new_name: RemoteNewNameArg
    ) -> RemoteRenameMachineOutput:
        """Rename a remote worker machine. Use to give a connected worker a clearer stable name before issuing remote jobs. This changes the control-server name used by later remote_* calls."""
        return rename_remote_machine(machine, new_name)

    @mcp.tool(
        structured_output=True,
        meta=remote_facade_meta,
        description=_description(
            """Run a high-level operation on a selected remote worker. Prefer this facade for normal remote reads, searches, line edits, shell commands, jobs, and workspace operations. Keep remote_invite, remote_list_machines, transfer, and legacy remote_* tools for control-plane or specialized cases. Use op to choose the operation and args for operation-specific parameters; do not include machine inside args."""
        ),
    )
    async def remote(
        machine: RemoteMachineArg,
        op: RemoteFacadeOpArg,
        args: RemoteFacadeArgsArg,
    ) -> RemoteFacadeOutput:
        """Run a high-level operation on a remote worker."""
        return await remote_execute(machine, op, args)

    @mcp.tool(structured_output=True, meta=remote_read_meta)
    async def remote_environment_info(
        machine: RemoteMachineArg,
    ) -> EnvironmentInfoOutput:
        """Return workspace, auth, policy, and basic environment information from a remote worker. Use to verify the remote machine, working directory, runtime versions, and limits before running remote commands or editing remote files."""
        return await _remote_typed(
            EnvironmentInfoOutput, machine, "environment_info", {}
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_execute_meta,
        description=_description(
            f"""Run one non-interactive shell command on a remote worker. Use for build, test, package-manager, git, and inspection commands that should finish promptly on that worker. Timeout: timeout_s is in seconds and should stay within the run_shell cap of {settings.run_shell_max_timeout_s} seconds on the worker. Output: max_output_bytes caps returned output and the worker default cap is max_output_bytes={settings.max_output_bytes}. For long-running or interactive remote processes, use start_remote_persistent_shell with send_remote_persistent_shell_input and read_remote_persistent_shell_output."""
        ),
    )
    async def run_remote_shell_command(
        machine: RemoteMachineArg,
        command: RemoteCommandArg,
        cwd: RemoteCwdArg = ".",
        timeout_s: RemoteTimeoutArg = None,
        max_output_bytes: int | None = None,
    ) -> RunShellCommandOutput:
        """Run one non-interactive shell command on a remote worker."""
        return await _remote_typed(
            RunShellCommandOutput,
            machine,
            "run_shell_command",
            {
                "command": command,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
            },
            timeout_s,
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_execute_meta,
        description=_description(
            f"""Write Python code to a temporary file and execute it on a remote worker. Use for short remote scripts, structured analysis, or file transformations that are easier in Python than shell. Parameters: cwd is resolved on the remote worker and timeout_s defaults to 60 seconds. Timeout: keep timeout_s within the run_shell cap of {settings.run_shell_max_timeout_s} seconds."""
        ),
    )
    async def run_remote_python_code(
        machine: RemoteMachineArg,
        code: RemotePythonCodeArg,
        cwd: RemoteCwdArg = ".",
        timeout_s: int = 60,
    ) -> RunPythonCodeOutput:
        """Write Python code to a temporary file and execute it on a remote worker."""
        return await _remote_typed(
            RunPythonCodeOutput,
            machine,
            "run_python_code",
            {"code": code, "cwd": cwd, "timeout_s": timeout_s},
            timeout_s,
        )

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def start_remote_persistent_shell(
        machine: RemoteMachineArg,
        cwd: RemoteCwdArg = ".",
        name: RemoteInviteNameArg = None,
        command: str | None = None,
    ) -> StartPersistentShellOutput:
        """Start a persistent shell session on a remote worker. Use for remote development servers, watches, REPLs, or interactive commands whose output must be read incrementally. For one-shot commands, use run_remote_shell_command."""
        return await _remote_typed(
            StartPersistentShellOutput,
            machine,
            "start_persistent_shell",
            {"cwd": cwd, "name": name, "command": command},
        )

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def send_remote_persistent_shell_input(
        machine: RemoteMachineArg,
        session_id: RemoteSessionIdArg,
        input_text: RemoteInputTextArg,
        enter: RemoteEnterArg = True,
    ) -> SendPersistentShellInputOutput:
        """Send input to a persistent remote shell session. Use after start_remote_persistent_shell when the remote process is waiting for commands or interactive input. enter=false sends partial input without a newline."""
        return await _remote_typed(
            SendPersistentShellInputOutput,
            machine,
            "send_persistent_shell_input",
            {
                "session_id": session_id,
                "input_text": input_text,
                "enter": enter,
            },
        )

    @mcp.tool(structured_output=True, meta=remote_read_meta)
    async def read_remote_persistent_shell_output(
        machine: RemoteMachineArg,
        session_id: RemoteSessionIdArg,
        lines: RemoteLinesArg = 200,
    ) -> ReadPersistentShellOutput:
        """Read recent output from a persistent remote shell session. Use to inspect output from remote long-running or interactive commands. lines bounds the returned recent output."""
        return await _remote_typed(
            ReadPersistentShellOutput,
            machine,
            "read_persistent_shell_output",
            {"session_id": session_id, "lines": lines},
        )

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def kill_remote_persistent_shell(
        machine: RemoteMachineArg, session_id: RemoteSessionIdArg
    ) -> KillPersistentShellOutput:
        """Terminate a persistent remote shell session. Use when a remote server, watch, REPL, or stuck command is no longer needed. This affects only the named session on the selected worker."""
        return await _remote_typed(
            KillPersistentShellOutput,
            machine,
            "kill_persistent_shell",
            {"session_id": session_id},
        )

    @mcp.tool(structured_output=True, meta=remote_read_meta)
    async def list_remote_persistent_shells(
        machine: RemoteMachineArg,
    ) -> ListPersistentShellsOutput:
        """List persistent shell sessions on a remote worker. Use before reading, sending to, or killing remote sessions when you need the session_id or active-process overview."""
        return await _remote_typed(
            ListPersistentShellsOutput, machine, "list_persistent_shells", {}
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_read_meta,
        description=_description(
            f"""List files and directories on a remote worker. Use for quick remote directory inspection. Parameters: path is resolved on the remote worker; recursive controls traversal. Result: returns file_info plus limit_count, count, and is_truncated to indicate whether the listing was complete within the limit. Limits: max_entries defaults to 500 and must be between 0 and max_directory_entries={settings.max_directory_entries}."""
        ),
    )
    async def remote_list_files(
        machine: RemoteMachineArg,
        path: RemotePathArg = ".",
        recursive: RemoteRecursiveArg = False,
        max_entries: RemoteMaxEntriesArg = 500,
    ) -> ListFilesOutput:
        """List files and directories on a remote worker."""
        return await _remote_typed(
            ListFilesOutput,
            machine,
            "list_files",
            {"path": path, "recursive": recursive, "max_entries": max_entries},
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_read_meta,
        description=_description(
            f"""Return a compact directory tree from a remote worker. Use to understand remote project layout before reading or editing files. Parameters: depth defaults to 3. Limits: max_entries defaults to 500 and is capped by max_tree_entries={settings.max_tree_entries}."""
        ),
    )
    async def remote_tree_view(
        machine: RemoteMachineArg,
        cwd: RemoteCwdArg = ".",
        depth: RemoteDepthArg = 3,
        max_entries: RemoteMaxEntriesArg = 500,
    ) -> TreeViewOutput:
        """Return a compact directory tree from a remote worker."""
        return await _remote_typed(
            TreeViewOutput,
            machine,
            "tree_view",
            {"cwd": cwd, "depth": depth, "max_entries": max_entries},
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_read_meta,
        description=_description(
            f"""Find files by glob pattern on a remote worker. Use when you know remote filename patterns and need matching paths. Parameters: cwd narrows the search root. Limits: max_results defaults to 500 and is capped by max_glob_results={settings.max_glob_results}."""
        ),
    )
    async def remote_glob_search(
        machine: RemoteMachineArg,
        pattern: RemotePatternArg,
        cwd: RemoteCwdArg = ".",
        max_results: RemoteMaxEntriesArg = 500,
    ) -> GlobSearchOutput:
        """Find files by glob pattern on a remote worker."""
        return await _remote_typed(
            GlobSearchOutput,
            machine,
            "glob_search",
            {"pattern": pattern, "cwd": cwd, "max_results": max_results},
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_read_meta,
        description=_description(
            f"""Search remote file contents using ripgrep. Use to locate symbols, usages, or text on a remote worker before reading or editing. Parameters: query is regex by default; glob, cwd, and case_sensitive narrow the search. Limits: max_results is optional and capped by max_grep_results={settings.max_grep_results}."""
        ),
    )
    async def remote_grep_search(
        machine: RemoteMachineArg,
        query: RemoteQueryArg,
        cwd: RemoteCwdArg = ".",
        glob: RemoteGlobArg = None,
        regex: RemoteRegexArg = True,
        case_sensitive: RemoteCaseSensitiveArg = True,
        max_results: RemoteMaxResultsArg = None,
    ) -> GrepSearchOutput:
        """Search remote file contents using ripgrep."""
        return await _remote_typed(
            GrepSearchOutput,
            machine,
            "grep_search",
            {
                "query": query,
                "cwd": cwd,
                "glob": glob,
                "regex": regex,
                "case_sensitive": case_sensitive,
                "max_results": max_results,
            },
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_read_meta,
        description=_description(
            f"""Read a UTF-8 text file, optionally by line range. Limits: per-file reads are capped by max_file_read_bytes={settings.max_file_read_bytes}."""
        ),
    )
    async def remote_read_file(
        machine: RemoteMachineArg,
        path: RemotePathArg,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ReadFileOutput:
        """Read a UTF-8 text file on a remote worker."""
        return await _remote_typed(
            ReadFileOutput,
            machine,
            "read_file",
            {
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
            },
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_read_meta,
        description=_description(
            f"""Read multiple UTF-8 text files on a remote worker with optional per-file line ranges. Use for targeted remote context gathering across known paths. Limits: max_read_many_files={settings.max_read_many_files}, max_read_many_total_bytes={settings.max_read_many_total_bytes}."""
        ),
    )
    async def remote_read_many_files(
        machine: RemoteMachineArg,
        files: ReadFilesArg,
    ) -> ReadManyFilesOutput:
        """Read multiple UTF-8 text files on a remote worker."""
        return await _remote_typed(
            ReadManyFilesOutput,
            machine,
            "read_many_files",
            {
                "files": [
                    file.model_dump()
                    for file in TypeAdapter(ReadFilesArg).validate_python(files)
                ]
            },
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_write_meta,
        description=_description(
            f"""Write a UTF-8 text file on a remote worker. Use to create or intentionally replace a whole remote file. Parameters: overwrite=false protects existing files. Limits: writes are capped by max_file_write_bytes={settings.max_file_write_bytes}. For precise changes, use remote_edit_file or remote_apply_patch."""
        ),
    )
    async def remote_write_file(
        machine: RemoteMachineArg,
        path: RemotePathArg,
        content: RemoteContentArg,
        overwrite: RemoteOverwriteArg = True,
    ) -> WriteFileOutput:
        """Write a UTF-8 text file on a remote worker."""
        return await _remote_typed(
            WriteFileOutput,
            machine,
            "write_file",
            {"path": path, "content": content, "overwrite": overwrite},
        )

    @mcp.tool(
        structured_output=True,
        meta=remote_write_meta,
        description=_description(
            f"""Replace exact text in a remote file. Use for small precise remote edits after reading the target file. Parameters: old must match exactly; replace_all=true should be used only when every exact occurrence should change. Limits: writes are capped by max_file_write_bytes={settings.max_file_write_bytes}."""
        ),
    )
    async def remote_edit_file(
        machine: RemoteMachineArg,
        path: RemotePathArg,
        old: RemoteOldTextArg,
        new: RemoteNewTextArg,
        replace_all: RemoteReplaceAllArg = False,
    ) -> EditFileOutput:
        """Replace exact text in a remote file."""
        return await _remote_typed(
            EditFileOutput,
            machine,
            "edit_file",
            {"path": path, "old": old, "new": new, "replace_all": replace_all},
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_multi_edit_file(
        machine: RemoteMachineArg, path: RemotePathArg, edits: RemoteEditsArg
    ) -> MultiEditFileOutput:
        """Apply multiple exact-text edits to one remote file. Use when several small remote replacements should be made together. Each edit needs old, new, and optional replace_all; read the file first to avoid stale or ambiguous edits."""
        return await _remote_typed(
            MultiEditFileOutput,
            machine,
            "multi_edit_file",
            {"path": path, "edits": edits},
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_delete_file_or_dir(
        machine: RemoteMachineArg,
        path: RemotePathArg,
        recursive: RemoteRecursiveArg = False,
    ) -> DeleteFileOrDirOutput:
        """Delete a file or directory on a remote worker. Use only when remote removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
        return await _remote_typed(
            DeleteFileOrDirOutput,
            machine,
            "delete_file_or_dir",
            {"path": path, "recursive": recursive},
        )

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_job_start(
        machine: RemoteMachineArg,
        command: JobCommandArg,
        cwd: JobCwdArg = ".",
        name: JobNameArg = None,
        purpose: ToolPurposeArg = None,
        explanation: ToolExplanationArg = None,
    ) -> JobStartOutput:
        """Start a non-interactive command as a tracked job on a remote worker. Use remote_job_start for long-running remote builds, tests, servers, watches, experiments, and other commands you want to manage by job_id with remote_job_list, remote_job_tail, remote_job_stop, or remote_job_retry. Use start_remote_persistent_shell instead when the remote process is interactive, needs later send_remote_persistent_shell_input calls, or should be managed directly by session_id. Use run_remote_shell_command for short bounded remote commands."""
        return await _remote_typed(
            JobStartOutput,
            machine,
            "job_start",
            {
                "command": command,
                "cwd": cwd,
                "name": name,
                "purpose": purpose,
                "explanation": explanation,
            },
        )

    @mcp.tool(structured_output=True, meta=remote_read_meta)
    async def remote_job_list(
        machine: RemoteMachineArg, include_finished: IncludeFinishedArg = True
    ) -> JobListOutput:
        """List tracked non-interactive jobs and status counts on a remote worker. Use this for commands started with remote_job_start/remote_job_retry; use list_remote_persistent_shells for manually managed interactive remote sessions. Each job is a recorded persistent-shell command on that worker, not a central scheduler queue."""
        return await _remote_typed(
            JobListOutput,
            machine,
            "job_list",
            {"include_finished": include_finished},
        )

    @mcp.tool(structured_output=True, meta=remote_read_meta)
    async def remote_job_tail(
        machine: RemoteMachineArg,
        job_id: JobIdArg,
        lines: JobTailLinesArg = 200,
    ) -> JobTailOutput:
        """Read recent terminal output for a tracked remote non-interactive job by job_id. Use this instead of read_remote_persistent_shell_output for jobs started with remote_job_start because it refreshes job status and hides the backing session_id. Full logs are not persisted separately, so output may be unavailable after the remote backing session exits or is lost."""
        return await _remote_typed(
            JobTailOutput,
            machine,
            "job_tail",
            {"job_id": job_id, "lines": lines},
        )

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_job_stop(
        machine: RemoteMachineArg, job_id: JobIdArg
    ) -> JobStopOutput:
        """Stop a tracked remote non-interactive job by killing its backing persistent shell session on the selected worker and updating the job record. Use kill_remote_persistent_shell only for manually managed remote sessions started with start_remote_persistent_shell. The job record remains available for list and retry."""
        return await _remote_typed(
            JobStopOutput, machine, "job_stop", {"job_id": job_id}
        )

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_job_retry(
        machine: RemoteMachineArg,
        job_id: JobIdArg,
        purpose: ToolPurposeArg = None,
        explanation: ToolExplanationArg = None,
    ) -> JobRetryOutput:
        """Restart a terminal tracked job on a remote worker with its original command and working directory. Use this for failed or completed non-interactive jobs started with remote_job_start; for interactive remote sessions, start a new persistent shell manually instead. This creates a new backing persistent shell session on that worker and keeps the same job_id."""
        return await _remote_typed(
            JobRetryOutput,
            machine,
            "job_retry",
            {
                "job_id": job_id,
                "purpose": purpose,
                "explanation": explanation,
            },
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_copy_file(
        src_machine: RemoteSourceMachineArg,
        src_path: RemoteSourcePathArg,
        dst_machine: RemoteDestinationMachineArg,
        dst_path: RemoteDestinationPathArg,
        overwrite: RemoteOverwriteArg = True,
        chunk_size: RemoteChunkSizeArg = None,
    ) -> RemoteCopyFileOutput:
        """Copy one file between two remote worker machines through the control server. Use for binary-safe remote-to-remote transfer. Parameters: src_machine and dst_machine are exact names from remote_list_machines; src_path is the source file on src_machine; dst_path is the destination file path on dst_machine; overwrite controls replacing an existing destination file; chunk_size optionally overrides the transfer chunk size and usually should be omitted."""
        return await copy_remote_file_to_remote(
            src_machine,
            src_path,
            dst_machine,
            dst_path,
            overwrite,
            chunk_size,
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_copy_dir(
        src_machine: RemoteSourceMachineArg,
        src_path: RemoteSourcePathArg,
        dst_machine: RemoteDestinationMachineArg,
        dst_path: RemoteDestinationPathArg,
        overwrite: RemoteOverwriteArg = False,
        chunk_size: RemoteChunkSizeArg = None,
    ) -> RemoteCopyDirOutput:
        """Copy a directory tree between two remote worker machines through the control server. Parameters: src_machine and dst_machine are exact names from remote_list_machines; src_path is the source directory; dst_path is the destination directory; overwrite controls replacing an existing destination; chunk_size usually should be omitted."""
        return await copy_remote_dir_to_remote(
            src_machine,
            src_path,
            dst_machine,
            dst_path,
            overwrite,
            chunk_size,
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_pull_file(
        machine: RemoteMachineArg,
        remote_path: RemotePathArg,
        local_path: LocalPathArg,
        overwrite: RemoteOverwriteArg = True,
        chunk_size: RemoteChunkSizeArg = None,
    ) -> RemoteCopyFileOutput:
        """Copy one file from a remote worker into the control server workspace. Parameters: machine is the exact remote name from remote_list_machines; remote_path is the source file on that worker; local_path is the local destination file; overwrite controls replacing an existing local file; chunk_size usually should be omitted."""
        return await copy_remote_file_to_local(
            machine, remote_path, local_path, overwrite, chunk_size
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_push_file(
        local_path: LocalPathArg,
        machine: RemoteMachineArg,
        remote_path: RemotePathArg,
        overwrite: RemoteOverwriteArg = True,
        chunk_size: RemoteChunkSizeArg = None,
    ) -> RemoteCopyFileOutput:
        """Copy one file from the control server workspace to a remote worker. Parameters: local_path is the source file in the local workspace; machine is the exact remote name from remote_list_machines; remote_path is the target file on that worker; overwrite controls replacing an existing remote file; chunk_size usually should be omitted."""
        return await copy_local_file_to_remote(
            local_path, machine, remote_path, overwrite, chunk_size
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_pull_dir(
        machine: RemoteMachineArg,
        remote_path: RemotePathArg,
        local_path: LocalPathArg,
        overwrite: RemoteOverwriteArg = False,
        chunk_size: RemoteChunkSizeArg = None,
    ) -> RemoteCopyDirOutput:
        """Copy a directory tree from a remote worker into the control server workspace. Parameters: machine is the exact remote name from remote_list_machines; remote_path is the source directory on that worker; local_path is the local target directory; overwrite controls replacing an existing local target; chunk_size usually should be omitted."""
        return await copy_remote_dir_to_local(
            machine, remote_path, local_path, overwrite, chunk_size
        )

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_push_dir(
        local_path: LocalPathArg,
        machine: RemoteMachineArg,
        remote_path: RemotePathArg,
        overwrite: RemoteOverwriteArg = False,
        chunk_size: RemoteChunkSizeArg = None,
    ) -> RemoteCopyDirOutput:
        """Copy a directory tree from the control server workspace to a remote worker. Parameters: local_path is the source directory in the local workspace; machine is the exact remote name from remote_list_machines; remote_path is the target directory; overwrite controls replacing an existing target; chunk_size usually should be omitted."""
        return await copy_local_dir_to_remote(
            local_path, machine, remote_path, overwrite, chunk_size
        )

    @mcp.tool(structured_output=True, meta=remote_patch_meta)
    async def remote_apply_patch(
        machine: RemoteMachineArg,
        patch: RemotePatchArg,
        cwd: RemoteCwdArg = ".",
    ) -> ApplyPatchOutput:
        """Apply a unified diff on a remote worker using git apply. Use for larger remote edits, multi-file changes, additions, and deletions when a patch is clearer than exact replacements. cwd controls where patch paths resolve on the remote worker."""
        return await _remote_typed(
            ApplyPatchOutput,
            machine,
            "apply_patch",
            {"patch": patch, "cwd": cwd},
        )
