# Remote workers

Remote workers let the control server run normal session-bound code work on another machine. Use them when the connected ChatGPT session should coordinate work on a GPU box, lab machine, build host, or remote checkout while keeping one public MCP connector.

## How it works

1. The MCP client calls `remote_admin(action="invite", args={...})` on the control server.
2. The server returns a one-time shell command containing an invite code.
3. You paste that command on the remote machine.
4. The remote machine downloads a digest-qualified worker bundle manifest, verifies and installs the bundle into its persistent state directory, starts the worker, registers once, then long-polls for jobs.
5. The worker persists its identity locally and resumes the same registration after restart. While a long tool call runs, it sends heartbeats independently of job execution.
6. Each upgraded worker poll reports protocol, package version, bundle version, and the digest of the runtime that is actually executing. The controller requests an idle-time upgrade before dequeuing work when that digest differs from its current bundle.
7. The MCP client uses `remote_admin(action="list", args={})` to discover the registered machine name, then `session_start(target="remote", machine=..., workdir=...)` to start remote work.

Remote worker enrollment routes are public so the worker can join. Treat invite commands as sensitive and short-lived. The control server persists worker registrations in `state_dir/remote-workers.json` with a backup copy; unreadable primary state is recovered from the backup, while two invalid copies make remote management fail instead of silently forgetting trusted workers.

## Requirements

Control server:

- Public `LOCAL_SHELL_MCP_BASE_URL` must be reachable from the remote machine.
- `LOCAL_SHELL_MCP_REMOTE_ENABLED=true`.
- OAuth still protects normal MCP/REST tool calls.

Remote machine:

- `curl` plus Python 3.14 or newer are required. When Python is unavailable, the join script can use an existing `uv` or download a temporary `uv` installer to provision Python 3.14.
- The selected working directory should exist or be creatable by the user running the worker.
- The worker state directory defaults to `$XDG_STATE_HOME/local-shell-mcp-worker` or `~/.local/state/local-shell-mcp-worker`; override it with `LOCAL_SHELL_MCP_WORKER_STATE_DIR`.
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

## Start an installed worker manually

If `local-shell-mcp` is already installed on the remote machine, enroll it once with:

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --invite lsmcp_inv_xxxxx \
  --name gpu1 \
  --workdir /home/me/project
```

The `--server` value is the public origin, not `/mcp`. After a successful enrollment, the worker can resume from its persisted identity without placing either the invite or access token in a restart command:

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --name gpu1 \
  --workdir /home/me/project
```

## Lifecycle safety

One worker state directory permits one active worker process. The worker acquires `worker.lock` before it resumes or consumes an invite, so an accidental second manual process fails before it can create a duplicate registration or compete for jobs. The operating system releases the lock after a crash or forced exit. Existing systemd or launchd workers are recognized by their service PID and may wait for an orderly handoff instead of failing immediately.

Automatic runtime upgrades preserve the same lock across process replacement. POSIX workers inherit the locked file descriptor through `exec`; Windows workers inherit the native file handle, wait for the parent to release its byte-range lock, then reacquire it before reconnecting. The access token is never added to restart arguments.

Registration and resume responses advertise the controller's long-poll timeout. Each worker adds a small transport grace period, sends a bounded `curl` request with a separate connection timeout, and advertises its own deadline back to the controller. The controller uses the shorter deadline and returns its current value on every poll, so timeout changes take effect without restarting the worker.

## Automatic runtime upgrades

Poll protocol version 1 negotiates the actual worker bundle digest. A worker that reports the current digest receives normal heartbeat and job responses. A worker that reports a different digest receives a required upgrade instruction instead of a job, so runtime replacement only happens while the worker is idle. Legacy workers that send no versioned poll payload keep their existing heartbeat and job behavior; restart them through a current join command to opt into automatic upgrades.

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
