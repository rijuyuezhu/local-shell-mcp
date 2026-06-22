"""Server-side state and coordination for remote workers."""

import asyncio
import contextlib
import json
import os
import secrets
import shlex
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..audit import audit
from ..config.settings import get_settings
from .constants import REMOTE_JOIN_PATH, REMOTE_WORKER_REGISTRY_FILE_NAME
from .responses import _ok


def _utc() -> float:
    """Return a Unix timestamp used for invite and worker bookkeeping."""
    return time.time()


@dataclass
class RemoteInvite:
    """One-time enrollment token that allows a remote worker to register before expiry."""

    code: str
    """Opaque invite code presented by a joining remote worker."""
    name: str | None
    """Optional requested worker name for display and lookup."""
    workdir: str | None
    """Optional worker-side working directory requested for the connection."""
    expires_at: float
    """Unix timestamp after which the invite can no longer be used."""
    used: bool = False
    """Whether a worker has already consumed this one-time invite."""


@dataclass
class RemoteWorker:
    """Registered remote worker state, including polling queue, current job, and last heartbeat."""

    name: str
    """Stable worker name used in remote tool routing."""
    token: str
    """Bearer token used by the worker to poll for jobs and submit results."""
    workdir: str | None = None
    """Default working directory reported or requested for this worker."""
    created_at: float = field(default_factory=_utc)
    """Unix timestamp when the worker registered."""
    last_seen: float = field(default_factory=_utc)
    """Unix timestamp for the most recent worker poll or heartbeat."""
    status: str = "online"
    """Current worker availability state shown in remote status responses."""
    capabilities: list[str] = field(default_factory=list)
    """Capability names advertised by the worker."""
    info: dict[str, Any] = field(default_factory=dict)
    """Additional worker-provided diagnostic metadata."""
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    """Pending job queue consumed by the worker poll loop."""


class RemoteManager:
    """In-memory coordinator for remote worker invites, registration, polling, results, and tool calls."""

    def __init__(self) -> None:
        self.invites: dict[str, RemoteInvite] = {}
        self.workers: dict[str, RemoteWorker] = {}
        self.tokens: dict[str, str] = {}
        self.pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._registry_loaded_path: Path | None = None

    def _registry_path(self) -> Path:
        """Return the persisted worker registry path for the active settings."""
        return get_settings().state_dir / REMOTE_WORKER_REGISTRY_FILE_NAME

    def _load_registry_unlocked(self) -> None:
        """Load persisted workers once per active state directory."""
        path = self._registry_path()
        if self._registry_loaded_path == path:
            return
        self._registry_loaded_path = path
        self.workers = {}
        self.tokens = {}
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        rows = data.get("workers") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            access = str(item.get("access") or item.get("token") or "").strip()
            if (
                not name
                or not access
                or name in self.workers
                or access in self.tokens
            ):
                continue
            self.workers[name] = RemoteWorker(
                name=name,
                token=access,
                workdir=str(item.get("workdir") or ""),
                created_at=float(item.get("created_at") or _utc()),
                last_seen=0.0,
                status="offline",
                capabilities=list(item.get("capabilities") or []),
                info=dict(item.get("info") or {}),
            )
            self.tokens[access] = name

    def _save_registry_unlocked(self) -> None:
        """Persist registered workers without serializing volatile queues or pending calls."""
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "workers": [
                {
                    "name": worker.name,
                    "access": worker.token,
                    "workdir": worker.workdir,
                    "created_at": worker.created_at,
                    "capabilities": worker.capabilities,
                    "info": worker.info,
                }
                for worker in sorted(
                    self.workers.values(), key=lambda item: item.name
                )
            ],
        }
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
        with contextlib.suppress(OSError):
            tmp_path.chmod(0o600)
        tmp_path.replace(path)

    def _join_url(self) -> str:
        """Build the copy-paste registration command for a pending invite."""
        settings = get_settings()
        return settings.resolved_base_url + REMOTE_JOIN_PATH

    async def create_invite(
        self,
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
    ) -> dict[str, Any]:
        """Create a time-limited registration invitation and return the command used by a worker."""
        settings = get_settings()
        ttl = max(60, min(ttl_s or settings.remote_invite_ttl_s, 24 * 3600))
        code = "lsmcp_inv_" + secrets.token_urlsafe(24)
        invite = RemoteInvite(
            code=code, name=name, workdir=workdir, expires_at=_utc() + ttl
        )
        async with self._lock:
            self._load_registry_unlocked()
            self.invites[code] = invite
        command = f"curl -fsSL {shlex.quote(self._join_url())} | bash -s -- --invite {shlex.quote(code)}"
        if name:
            command += f" --name {shlex.quote(name)}"
        if workdir:
            command += f" --workdir {shlex.quote(workdir)}"
        return {
            "code": code,
            "name": name,
            "workdir": workdir,
            "expires_at": invite.expires_at,
            "ttl_s": ttl,
            "join_url": self._join_url(),
            "command": command,
        }

    async def register_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate an invite token and attach a newly started worker to the manager."""
        code = str(payload.get("invite") or "")
        requested_name = str(payload.get("name") or "").strip() or None
        async with self._lock:
            self._load_registry_unlocked()
            invite = self.invites.get(code)
            if not invite:
                raise ValueError("invalid invite code")
            if invite.used:
                raise ValueError("invite code has already been used")
            if invite.expires_at < _utc():
                raise ValueError("invite code has expired")
            name = (
                requested_name
                or invite.name
                or self._default_machine_name(payload)
            )
            if invite.name and requested_name and requested_name != invite.name:
                raise ValueError(
                    f"invite is bound to machine name {invite.name!r}"
                )
            if name in self.workers:
                raise ValueError(f"machine name already exists: {name}")
            token = "lsmcp_wk_" + secrets.token_urlsafe(32)
            worker = RemoteWorker(
                name=name,
                token=token,
                workdir=str(payload.get("workdir") or invite.workdir or ""),
                capabilities=list(payload.get("capabilities") or []),
                info=dict(payload.get("info") or {}),
            )
            self.workers[name] = worker
            self.tokens[token] = name
            invite.used = True
            self._save_registry_unlocked()
        audit("remote_worker_registered", machine=name)
        return {"token": token, "name": name, "poll_interval_s": 0}

    async def resume_worker(
        self, token: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Reconnect a worker using a persisted worker identity instead of consuming a new invite."""
        async with self._lock:
            self._load_registry_unlocked()
            name = self.tokens.get(token)
            if not name:
                raise PermissionError("invalid worker identity")
            worker = self.workers.get(name)
            if not worker:
                raise PermissionError("worker identity is no longer valid")
            requested_name = str(payload.get("name") or "").strip()
            if requested_name and requested_name != name:
                raise ValueError(f"worker identity belongs to machine {name!r}")
            worker.status = "online"
            worker.last_seen = _utc()
            worker.workdir = str(payload.get("workdir") or worker.workdir or "")
            worker.capabilities = list(
                payload.get("capabilities") or worker.capabilities
            )
            worker.info = dict(payload.get("info") or worker.info)
            self._save_registry_unlocked()
        audit("remote_worker_resumed", machine=name)
        return {"token": token, "name": name, "poll_interval_s": 0}

    def _default_machine_name(self, payload: dict[str, Any]) -> str:
        """Choose a stable human-readable worker name when the worker did not provide one."""
        raw_info = payload.get("info")
        info = raw_info if isinstance(raw_info, dict) else {}
        user = info.get("user") or os.getenv("USER") or "user"
        host = info.get("hostname") or "remote"
        base = f"{user}@{host}"
        if base not in self.workers:
            return base
        index = 2
        while f"{base}-{index}" in self.workers:
            index += 1
        return f"{base}-{index}"

    async def poll(self, token: str) -> dict[str, Any]:
        """Hold a worker poll request until a job is available or the long-poll timeout expires."""
        worker = self._worker_by_token(token)
        worker.status = "online"
        worker.last_seen = _utc()
        try:
            job = await asyncio.wait_for(
                worker.queue.get(), timeout=get_settings().remote_poll_timeout_s
            )
            return {"job": job}
        except TimeoutError:
            return {"job": None, "heartbeat": True}

    async def submit_result(
        self, token: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Accept a worker result and wake the caller waiting for that job."""
        worker = self._worker_by_token(token)
        worker.status = "online"
        worker.last_seen = _utc()
        job_id = str(payload.get("job_id") or "")
        future = self.pending.pop(job_id, None)
        if future and not future.done():
            future.set_result(payload)
        return {"accepted": bool(future)}

    async def call(
        self,
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        """Send one tool invocation to a worker and wait for its result with timeout handling."""
        self._load_registry_unlocked()
        worker = self.workers.get(machine)
        if not worker:
            raise ValueError(f"unknown remote machine: {machine}")
        if _utc() - worker.last_seen > max(
            2 * get_settings().remote_poll_timeout_s, 60
        ):
            worker.status = "offline"
            raise RuntimeError(f"remote machine is offline: {machine}")
        job_id = "job_" + uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[job_id] = future
        await worker.queue.put({"id": job_id, "tool": tool, "args": args})
        try:
            result = await asyncio.wait_for(
                future, timeout=timeout_s or get_settings().remote_job_timeout_s
            )
        except TimeoutError as exc:
            self.pending.pop(job_id, None)
            raise TimeoutError(
                f"remote job timed out: {tool} on {machine}"
            ) from exc
        if not result.get("ok", False):
            return _ok(
                {
                    "status": "error",
                    "error_type": result.get("error", "remote_error"),
                    "message": result.get("message", "remote job failed"),
                }
            )
        return _ok(result.get("data"))

    def list_machines(self) -> dict[str, Any]:
        """Return worker inventory and heartbeat-derived status for remote management tools."""
        self._load_registry_unlocked()
        now = _utc()
        offline_after_s = max(2 * get_settings().remote_poll_timeout_s, 60)
        rows = []
        counts = {"online": 0, "offline": 0}
        for worker in self.workers.values():
            last_seen_age_s = (
                None
                if not worker.last_seen
                else max(0.0, now - worker.last_seen)
            )
            status = (
                "online"
                if last_seen_age_s is not None
                and last_seen_age_s <= offline_after_s
                else "offline"
            )
            worker.status = status
            counts[status] += 1
            rows.append(
                {
                    "name": worker.name,
                    "status": status,
                    "workdir": worker.workdir,
                    "last_seen": worker.last_seen,
                    "last_seen_age_s": last_seen_age_s,
                    "offline_after_s": offline_after_s,
                    "queue_depth": worker.queue.qsize(),
                    "capabilities": worker.capabilities,
                    "info": worker.info,
                }
            )
        rows.sort(key=lambda item: (item["status"] != "online", item["name"]))
        return {"machines": rows, "counts": {**counts, "total": len(rows)}}

    def revoke(self, machine: str) -> dict[str, Any]:
        """Remove a registered worker and invalidate its polling token."""
        self._load_registry_unlocked()
        worker = self.workers.pop(machine, None)
        if not worker:
            raise ValueError(f"unknown remote machine: {machine}")
        self.tokens.pop(worker.token, None)
        self._save_registry_unlocked()
        return {"machine": machine, "revoked": True}

    def rename(self, machine: str, new_name: str) -> dict[str, Any]:
        """Rename a registered worker while preserving its token and job state."""
        self._load_registry_unlocked()
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("new_name is required")
        if new_name in self.workers:
            raise ValueError(f"machine name already exists: {new_name}")
        worker = self.workers.pop(machine, None)
        if not worker:
            raise ValueError(f"unknown remote machine: {machine}")
        worker.name = new_name
        self.workers[new_name] = worker
        self.tokens[worker.token] = new_name
        self._save_registry_unlocked()
        return {"old_name": machine, "new_name": new_name}

    def _worker_by_token(self, token: str) -> RemoteWorker:
        """Resolve a bearer token to the worker currently authorized to poll or submit results."""
        self._load_registry_unlocked()
        name = self.tokens.get(token)
        if not name:
            raise PermissionError("invalid worker token")
        worker = self.workers.get(name)
        if not worker:
            raise PermissionError("worker token is no longer valid")
        return worker


REMOTE_MANAGER = RemoteManager()


def remote_manager() -> RemoteManager:
    """Return the process-wide remote manager used by HTTP endpoints and MCP tools."""
    return REMOTE_MANAGER
