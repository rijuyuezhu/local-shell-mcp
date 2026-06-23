"""MCP tool registration for remote-worker proxy tools."""

import inspect
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

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
from ...schemas.input_models.remote import (
    LocalPathArg,
    RemoteChunkSizeArg,
    RemoteDestinationMachineArg,
    RemoteDestinationPathArg,
    RemoteEnterArg,
    RemoteFacadeArgsArg,
    RemoteFacadeOpArg,
    RemoteInputTextArg,
    RemoteInviteNameArg,
    RemoteInviteTtlArg,
    RemoteLinesArg,
    RemoteMachineArg,
    RemoteNewNameArg,
    RemoteOverwriteArg,
    RemotePathArg,
    RemoteSessionIdArg,
    RemoteSourceMachineArg,
    RemoteSourcePathArg,
    RemoteTimeoutArg,
    RemoteWorkdirArg,
)
from ...schemas.result_models.remote import (
    RemoteCopyDirOutput,
    RemoteCopyFileOutput,
    RemoteFacadeOutput,
    RemoteInviteOutput,
    RemoteListMachinesOutput,
    RemoteRenameMachineOutput,
    RemoteRevokeMachineOutput,
)
from ...schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    SendPersistentShellInputOutput,
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
