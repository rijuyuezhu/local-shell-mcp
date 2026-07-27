# Remote workers

Remote workers let the control server run normal session-bound code work on another machine. Use them when the connected ChatGPT session should coordinate work on a GPU box, lab machine, build host, or remote checkout while keeping one public MCP connector.

## How it works

1. The MCP client calls `remote_admin(action="invite", args={...})` on the control server.
2. The server returns a one-time shell command containing an invite code.
3. You paste that command on the remote machine.
4. The remote machine creates an independent profile, downloads a digest-qualified worker manifest, verifies the source bundle, and installs that immutable runtime under `runtimes/<sha256>`.
5. The profile stores its private controller identity separately under `profiles/<profile-id>`, while profiles using the same bundle digest share one runtime installation.
6. A stable credential-free launcher selects the profile's recorded digest and starts the verified runtime. The worker resumes the same registration after restart and sends heartbeats independently of long-running jobs.
7. Enrollment, resume, and every poll report the managed-runtime protocol, bundle version, and executing digest. The controller rejects source checkouts, incomplete reports, and legacy poll protocols before they can receive jobs. A stale managed digest receives an idle-time upgrade instruction.
8. The MCP client uses `remote_admin(action="list", args={})` to discover the registered machine name, then `session_start(target="remote", machine=..., workdir=...)` to start remote work.

Remote worker enrollment routes are public so the worker can join. Treat invite commands as sensitive and short-lived. The control server persists worker registrations in `state_dir/remote-workers.json` with a backup copy; unreadable primary state is recovered from the backup, while two invalid copies make remote management fail instead of silently forgetting trusted workers.

## Requirements

Control server:

- Public `LOCAL_SHELL_MCP_BASE_URL` must be reachable from the remote machine.
- `LOCAL_SHELL_MCP_REMOTE_ENABLED=true`.
- OAuth still protects normal MCP/REST tool calls.

Remote machine:

- `curl` plus Python 3.14 or newer are required. When Python is unavailable, the join script can use an existing `uv` or download a temporary `uv` installer to provision Python 3.14.
- The selected working directory should exist or be creatable by the user running the worker.
- The worker state directory defaults to `$XDG_STATE_HOME/local-shell-mcp-worker` or `~/.local/state/local-shell-mcp-worker`; override it with `LOCAL_SHELL_MCP_WORKER_STATE_DIR`. Keep the same value when reconnecting or managing a service.
- The worker inherits the remote machine's installed tools such as Git, compilers, CUDA tooling, and package managers.

## Create an invite

Ask the connected MCP client:

```text
Use local-shell-mcp to create a remote worker invite named gpu1 with workdir /home/me/project.
```

Equivalent tool call shape:

```json
{
  "action": "invite",
  "args": {
    "name": "gpu1",
    "workdir": "/home/me/project",
    "ttl_s": 600
  }
}
```

The server returns a command like:

```bash
curl -fsSL https://your-public-host.example.com/join | bash -s -- --invite lsmcp_inv_xxxxx --name gpu1 --workdir /home/me/project
```

Paste it on the remote machine. The generated invite is one-time use and expires after the configured TTL.

## Profiles and reconnecting

Every generated invite creates a profile id such as `p_0123456789abcdef`. Multiple invite commands may be run on the same host and state directory; each profile has an independent identity and process lock, while verified runtimes are shared by digest.

The bootstrap prints a reconnect command after enrollment. It has this shape on POSIX systems:

```bash
~/.local/state/local-shell-mcp-worker/run p_0123456789abcdef
```

On native Windows it uses `run.cmd`. The command contains no invite, worker access credential, server URL, machine name, or workdir. It reads the profile metadata, validates the recorded runtime, and then starts that exact managed bundle. The same command is available from:

- `remote_admin(action="reconnect_command", args={"machine": "gpu1"})`;
- the selected worker's **Copy reconnect command** action in the Web UI;
- the worker's initial enrollment output.

Temporary network or controller failures do not require manual action while the worker process remains alive: the poll loop retries with capped backoff. After a process exit or host restart, run the profile's reconnect command. A new invite is required after revocation or when the private profile identity has been deleted.

Do not enroll a normal package installation or source checkout directly. Current controllers require the generated managed-runtime report at enrollment and resume, so manually launched source workers are rejected before registration or job delivery.

## Migrate the legacy single-worker layout

Older installations stored one identity at the root of the worker state directory. Stop the old worker first, then migrate explicitly:

```bash
local-shell-mcp worker stop        # only when an old native service is installed
local-shell-mcp worker migrate
```

The command downloads and verifies the controller's current bundle using the saved server URL, creates one profile, installs the stable launcher, and prints JSON containing the new `profile_id` and reconnect command. Running `local-shell-mcp worker run` with no profile performs the same migration and immediately replaces itself with the verified profile runtime.

Migration is serialized against both the legacy worker process lock and a dedicated migration lock. It never starts a second poller with the same credential. The old root `identity.json`, `runtime/`, and `runtime.json` are retained for rollback; the migration marker contains only the profile id and timestamp. A partially created profile is removed on failure, and a complete orphaned profile is reused after interruption.

If the old controller registration was revoked, migrate cannot restore trust; create a new invite instead.

## Large `session_copy` transfers

`session_copy` remains the only public copy API. The controller selects the transport from the actual topology, worker capabilities, configured public origin, and measured payload size:

- local-to-local copies keep the local transactional path;
- copies within one remote worker keep the direct same-worker path;
- files below `remote_http_transfer_threshold_bytes`, workers without `http-transfer-v1`, or controllers without an explicit public `base_url` use the bounded JSON/base64 worker RPC path;
- capable large local/remote and cross-worker copies use the private resumable HTTP gateway. Cross-worker data is staged in an owner-private controller spool rather than granting either worker a callback into the other.

The measured default threshold is 1 MiB. Tune it with `remote_http_transfer_threshold_bytes`; related limits are `remote_http_transfer_chunk_bytes`, `remote_http_transfer_ticket_ttl_s`, `remote_http_transfer_max_active`, and `remote_http_transfer_max_spool_bytes`. Set `remote_http_transfer_enabled=false` to force the existing RPC/direct paths.

The route identifier is not a credential. Each operation receives a separate short-lived Authorization capability bound to the registered worker, direction, source/destination sessions, expected size and SHA-256, cursor, expiry, and active claim. Workers reject cross-origin, redirected, credential-bearing, query-bearing, and malformed URLs. Uploads use bounded `Content-Range` chunks with per-chunk digests; downloads use bounded `Range` requests from an immutable controller snapshot. The source-only runtime implements this with Python's standard library and requires no additional package.

Foreground failures and cancellation revoke capabilities and clean partial private state. Managed background copy jobs retain only validated spool/destination progress, clear active capabilities, and rotate new capabilities when the same durable job is retried. Controller spools are bound to platform-native file identity plus a refreshed ctime/mtime generation; POSIX uses no-follow opens and Windows rejects symlink/junction reparse points through the native handle before any bytes are read or written. Final publication still uses the existing transactional destination writer and whole-object digest check. Results report the actual `transport` and `resumed_bytes`.

## Install a user service

On Linux with a working `systemd --user` session, or on macOS with launchd, install and start a reboot/session-persistent worker with:

```bash
local-shell-mcp worker install-service p_0123456789abcdef
local-shell-mcp worker status
```

There is one native worker service per user state directory, so installing it with another profile id deliberately rebinds that service. Other profiles may still run in the foreground through their reconnect commands. Legacy root identities may omit the profile argument, but migrated and newly invited workers should bind an explicit profile.

On macOS, the generated launchd plist uses an explicit sanitized `PATH` that includes standard Homebrew locations and absolute entries exported by the GUI launchd session. PATH repair refreshes the plist without rewriting or dropping the profile-bound launcher.

Use `--no-start` to install and enable without starting. Lifecycle and diagnostics commands are:

```bash
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker logs --lines 100
local-shell-mcp worker logs --follow
local-shell-mcp worker uninstall-service
```

Lifecycle mutations and status return versioned JSON. Linux uses `~/.config/systemd/user/local-shell-mcp-worker.service` and `journalctl --user`; macOS uses `~/Library/LaunchAgents/com.fwerkor.local-shell-mcp-worker.plist` plus a private bounded log under the worker state directory. Windows reports `unsupported` for native service management and does not create an untracked detached process; use the profile reconnect command from the desired startup mechanism instead.
The systemd unit starts whenever that user's systemd manager starts. For pre-login startup after reboot, an administrator must deliberately enable user lingering, for example `loginctl enable-linger USER`; the worker CLI does not silently change linger policy.

Units and plists invoke a stable private launcher bound to one profile id and runtime digest. They contain only the Python executable, launcher path, canonical workdir, state-directory location, profile id, digest, and a managed-runtime marker. The invite, worker access token, server URL, and worker name remain exclusively in the private profile identity file.

## Update an installed runtime

Check and install the controller's latest verified source bundle with:

```bash
local-shell-mcp worker update p_0123456789abcdef
```

`--force` reinstalls the current digest. The command reuses the same same-origin redirect policy, size and SHA-256 verification, safe extraction, numeric downgrade protection, atomic replacement, and rollback used by automatic idle-time upgrades. For a profile, it atomically updates `profile.json` and refreshes the native service launcher to the new digest. It restarts the service only when its definition or runtime changed and that service was running before the update.

## Lifecycle safety

Each profile owns `profiles/<profile-id>/worker.lock`, so distinct profiles may run concurrently while a second process for the same profile fails before it can compete for jobs. The legacy root identity keeps its old root `worker.lock`. Migration requires that legacy lock to be free. The operating system releases locks after a crash or forced exit. Managed systemd or launchd workers are recognized by their service PID and may wait for an orderly upgrade/restart handoff instead of failing immediately.

Runtime installation is separately serialized by `install.lock`. Immutable `runtimes/<sha256>` directories are reused across profiles only after their metadata and required files pass validation. A failed install cannot replace a complete digest directory.

Automatic runtime upgrades preserve the profile lock across process replacement. POSIX workers inherit the locked file descriptor through `exec`; Windows workers inherit the native file handle, wait for the parent to release its byte-range lock, then reacquire it before reconnecting. The access token is never added to restart arguments. A managed profile upgrade also rewrites the service launcher before re-exec, preventing a later reboot from falling back to the old digest or legacy identity.

Registration and resume responses advertise the controller's long-poll timeout. Each worker adds a small transport grace period, sends a bounded `curl` request with a separate connection timeout, and advertises its own deadline back to the controller. The controller uses the shorter deadline and returns its current value on every poll, so timeout changes take effect without restarting the worker.

## Automatic runtime upgrades

Poll protocol version 2 requires a complete `managed_bundle` report and the full executing SHA-256 digest on every request. A worker that reports the current digest receives normal heartbeat and job responses. A worker that reports a different managed digest receives a required upgrade instruction instead of a job, so runtime replacement only happens while the worker is idle. Empty payloads, source-runtime reports, and protocol versions 0 or 1 receive a compatibility conflict and do not dequeue queued work.

Registration and resume apply the same managed-runtime gate. Existing legacy state can be converted with `worker migrate`; an old process itself cannot continue polling against a strict controller.

The controller manifest contains a schema version, bundle version, SHA-256 digest, byte size, and digest-qualified URL. Manifest and bundle responses use `Cache-Control: no-store`; the worker requests them with no-cache headers, rejects cross-origin URLs and redirects, verifies version, size, and digest, and refuses numeric version downgrades. The bundle remains a source-only allowlist rather than a copy of the controller package.

Installation extracts only bounded regular files and directories. Absolute paths, `..`, duplicates, symlinks, hardlinks, devices, and incomplete package layouts are rejected. The worker extracts into a temporary directory, atomically swaps the runtime, writes metadata with restricted permissions, and restores the previous runtime if any step fails. POSIX workers use process replacement; Windows workers spawn the verified runtime and exit. Restart arguments never contain the worker access token, which remains only in the persisted identity file.

Upgrade failures do not dequeue normal jobs. The worker continues polling with capped exponential backoff, logs credential-redacted diagnostics, and resets the retry counter after a non-upgrade poll.

## Verify connection

Ask the MCP client:

```text
Use local-shell-mcp to list remote machines, start a remote session on gpu1 in /home/me/project, then inspect the project.
```

The normal flow before remote edits is:

1. `remote_admin(action="list", args={})`
2. `session_start(target="remote", machine="gpu1", workdir="/home/me/project")`
3. `read(session_id=..., path=".")` or `search(session_id=..., pattern=..., paths=[...])`
4. `hashline_edit(session_id=..., input=...)` from copied hashline rows; use `edit_lines(session_id=..., ...)` only for exact structured range edits; use `apply_patch(session_id=..., patch=..., cwd=...)` only when you already have a portable unified diff or compatibility envelope
5. `bash(session_id=..., command=...)` for commands and validation


The structured orientation returned by remote `session_start` is generated by the worker, not inferred by the controller. Its canonical worker-side workspace root/workdir, Git state, instruction files, runtime identity, tool probes, capabilities, and policy are preserved while the controller substitutes only its public session id and configured machine name. `session_change_cwd(session_id=..., workdir=...)` also works for remote sessions: it changes the paired worker session, refreshes the same orientation, updates the controller's cached canonical workdir, and clears stale grounding snapshots.

## Run remote commands

Example prompt:

```text
Use local-shell-mcp on remote machine gpu1. Inspect /home/me/project, run git status, then run the test command you find in the project docs. Report results before editing files.
```

Use `bash(session_id=..., async_=true)` for long-running non-interactive remote jobs. Manage the returned `job_id` with `job(session_id=..., ...)`. Job metadata, terminal status, and bounded output are persisted by the remote worker, so later polls use the same remote session even after completion. Prefer bounded non-interactive commands for remote work.

## Revoke a worker

When a worker should no longer receive jobs:

```text
Use local-shell-mcp to revoke remote machine gpu1 with `remote_admin(action="revoke", args={"machine": "gpu1"})`.
```

This removes the worker from the control server. Reconnect it with a new invite if needed.

## Settings

| Setting | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | Enable remote worker routes and MCP tools |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | Default one-time invite lifetime |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | Long-poll timeout; also contributes to worker online/offline detection |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | Control-side remote job result timeout |
| `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `64` | Maximum queued or in-flight jobs per worker; timed-out jobs do not consume this capacity |

Disable remote mode with `--remote-enabled false` or `LOCAL_SHELL_MCP_REMOTE_ENABLED=false`.
