# Remote workers

Remote workers let one `workgate` control server run session-bound work on another machine. They are useful for GPU hosts, build machines, lab servers, or remote checkouts while keeping a single public MCP connector.

## Requirements

The control server needs a public `WORKGATE_BASE_URL` reachable from the remote machine and remote support enabled. Normal MCP and UI access should remain protected by OAuth.

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
Use workgate to create a remote worker invite named gpu1 with workdir /home/me/project.
```

The generated command is sensitive and expires after a short time. Paste it only on the intended machine. Enrollment prints a profile id and a reconnect command; keep the worker state directory private.

The selected remote workdir is user content: it is the filesystem context in which Workgate is allowed to work. Worker-owned files are stored separately. On Linux, new workers use:

```text
${XDG_STATE_HOME:-~/.local/state}/workgate/worker/   # identity, profiles, logs/state
${XDG_DATA_HOME:-~/.local/share}/workgate/worker/   # runtimes, launcher, stored Python
```

macOS and Windows use native per-user Workgate state/data locations. Clearing ordinary cache or runtime/temp storage does not remove an installed managed worker runtime.

If enrollment used a custom `WORKGATE_WORKER_STATE_DIR`, export the same value whenever you run the `workgate worker ...` lifecycle and update commands below. For compatibility with older layouts, an explicit `WORKGATE_WORKER_STATE_DIR` also owns worker runtime/data files unless `WORKGATE_WORKER_DATA_DIR` is set separately. The saved reconnect launcher and an installed native service preserve the selected roots internally, but a fresh administrative CLI process otherwise uses the platform defaults.

```bash
export WORKGATE_WORKER_STATE_DIR=/path/to/worker-state
# Optional when state and installed runtime data should use different roots:
export WORKGATE_WORKER_DATA_DIR=/path/to/worker-data
```

## Reconnect after a restart

Run the reconnect command printed during enrollment. It is also available from the worker's action menu in the browser UI or through `remote_admin(action="reconnect_command", ...)`.

Temporary network failures are retried while the worker process is running. A new invite is needed after revocation or after deleting the saved worker identity.

## Install a user service

Linux with `systemd --user` and macOS with launchd can keep one selected profile running as a per-user service:

```bash
workgate worker install-service p_0123456789abcdef
workgate worker status
```

On Linux, installing the `systemd --user` service does not by itself guarantee startup before that user logs in after a reboot. If the worker must be reachable before login, an administrator must enable lingering once for that user:

```bash
sudo loginctl enable-linger USER
```

Without lingering, the enabled worker service starts with the user's systemd manager after login.

Common lifecycle commands are:

```bash
workgate worker start
workgate worker stop
workgate worker restart
workgate worker logs --lines 100
workgate worker logs --follow
workgate worker uninstall-service
```

There is one native worker service per user state directory. Installing another profile rebinds that service; other profiles can still run in the foreground. The native service records both its state root and installed-data root, so startup does not depend on the service manager's CWD. Native Windows service management is not provided, so use the reconnect command from your preferred startup mechanism.

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

## Update

Update a profile's managed worker runtime with:

```bash
workgate worker update p_0123456789abcdef
```

Use `--force` only when you intentionally want to reinstall the current runtime.

Pre-Workgate worker installations are not migrated or adopted automatically. Leave their state untouched, remove or stop the old service separately if needed, then create a fresh Workgate invite and re-enroll the machine.

The 5.0-alpha state/data layout change also does not automatically move an older Workgate worker root such as `~/.local/state/workgate-worker`. To keep using that installation temporarily, set `WORKGATE_WORKER_STATE_DIR` to the old absolute root; compatibility mode keeps its runtimes and launcher there too. A clean re-enrollment uses the new split state/data defaults. If you migrate files manually instead, stop the managed service first and preserve owner-private permissions.

## Revoke a worker

Use the **Revoke** action in the browser UI or ask the MCP client:

```text
Use workgate to revoke remote machine gpu1.
```

A revoked worker cannot receive more jobs. Re-enrollment requires a new invite.

## Troubleshooting

- **Worker never appears online:** confirm the public base URL is reachable from the remote host and that the invite has not expired.
- **Worker was online before a reboot:** run the saved reconnect command or install the user service. On Linux, also enable systemd lingering if the worker must start before that user logs in.
- **Service fails to start:** inspect `workgate worker status` and `workgate worker logs --lines 100`.
- **A command or file action is missing:** verify the remote host has the required executable and that the selected worker supports the operation.
- **The worker is rejected after an old upgrade:** run `worker update`, migrate a legacy installation, or enroll again.

For exact CLI syntax, see [CLI reference](../reference/cli.md). For implementation and protocol work, see [Development](../development.md) and [Security](../security.md).
