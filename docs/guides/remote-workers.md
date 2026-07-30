# Remote workers

Remote workers let one `local-shell-mcp` control server run session-bound work on another machine. They are useful for GPU hosts, build machines, lab servers, or remote checkouts while keeping a single public MCP connector.

## Requirements

The control server needs a public `LOCAL_SHELL_MCP_BASE_URL` reachable from the remote machine and remote support enabled. Normal MCP and UI access should remain protected by OAuth.

The remote machine needs `curl` and a usable Python 3.14 environment or `uv`. The selected workdir must be accessible to the user running the worker. Tools such as Git, compilers, CUDA, and package managers come from that remote machine.

## Enroll a worker

The easiest path is the browser UI:

1. Open **Remotes**.
2. Create an invite with a machine name and workdir.
3. Copy the generated one-time command.
4. Run it on the remote machine.
5. Wait for the machine to appear online.

You can also ask the connected MCP client:

```text
Use local-shell-mcp to create a remote worker invite named gpu1 with workdir /home/me/project.
```

The generated command is sensitive and expires after a short time. Paste it only on the intended machine. Enrollment prints a profile id and a reconnect command; keep the worker state directory private.

## Reconnect after a restart

Run the reconnect command printed during enrollment. It is also available from the worker's action menu in the browser UI or through `remote_admin(action="reconnect_command", ...)`.

Temporary network failures are retried while the worker process is running. A new invite is needed after revocation or after deleting the saved worker identity.

## Install a user service

Linux with `systemd --user` and macOS with launchd can keep one selected profile running as a per-user service:

```bash
local-shell-mcp worker install-service p_0123456789abcdef
local-shell-mcp worker status
```

Common lifecycle commands are:

```bash
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker logs --lines 100
local-shell-mcp worker logs --follow
local-shell-mcp worker uninstall-service
```

There is one native worker service per user state directory. Installing another profile rebinds that service; other profiles can still run in the foreground. Native Windows service management is not provided, so use the reconnect command from your preferred startup mechanism.

## Use the remote machine

Ask the MCP client to list machines and start an explicit remote session:

```text
List remote machines. Start a remote session on gpu1 in /home/me/project, inspect the repository and its instructions, then run git status. Do not edit files yet.
```

After `session_start`, use the returned `session_id` with the normal read, search, edit, shell, job, Todo, and Audit tools. Use `session_change_cwd` to move that session to another allowed directory.

For long-running non-interactive commands, use asynchronous `bash` and poll the returned job. Prefer bounded commands when an interactive shell is unnecessary.

## Copy files

Use `session_copy` after starting both source and destination sessions:

```text
Copy results/summary.json from the gpu1 session into reports/gpu1-summary.json in my local session, then verify the destination.
```

The control server selects an available transfer method. Users normally do not need to tune transfer internals. For limits and advanced settings, see [Configuration](../reference/configuration.md).

## Update or migrate

Update a profile's managed worker runtime with:

```bash
local-shell-mcp worker update p_0123456789abcdef
```

Use `--force` only when you intentionally want to reinstall the current runtime.

Older single-worker installations can be migrated after stopping the old worker:

```bash
local-shell-mcp worker stop
local-shell-mcp worker migrate
```

If the old registration was revoked, create a new invite instead.

## Revoke a worker

Use the **Revoke** action in the browser UI or ask the MCP client:

```text
Use local-shell-mcp to revoke remote machine gpu1.
```

A revoked worker cannot receive more jobs. Re-enrollment requires a new invite.

## Troubleshooting

- **Worker never appears online:** confirm the public base URL is reachable from the remote host and that the invite has not expired.
- **Worker was online before a reboot:** run the saved reconnect command or install the user service.
- **Service fails to start:** inspect `local-shell-mcp worker status` and `local-shell-mcp worker logs --lines 100`.
- **A command or file action is missing:** verify the remote host has the required executable and that the selected worker supports the operation.
- **The worker is rejected after an old upgrade:** run `worker update`, migrate a legacy installation, or enroll again.

For exact CLI syntax, see [CLI reference](../reference/cli.md). For implementation and protocol work, see [Development](../development.md) and [Security](../security.md).
