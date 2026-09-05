"""Process-instance identity and managed-job liveness leases."""

import contextlib
import hashlib
import secrets
import threading
from pathlib import Path
from typing import Literal

from ..persistence import get_state_store
from .private_files import private_file_lock

PROCESS_INSTANCE_ID = secrets.token_hex(16)
"""Opaque id that changes whenever the server process starts."""

MANAGED_JOB_LEASE_VERSION = 1
MANAGED_JOB_LEASE_ACQUIRE_TIMEOUT_S = 5.0
MANAGED_JOB_LEASE_JOIN_TIMEOUT_S = 5.0
type ManagedJobLeaseState = Literal["live", "dead", "unknown"]


def managed_job_lease_path(job_id: str) -> Path:
    """Return one opaque owner-private lock path for a durable managed job."""
    directory = get_state_store().layout.locks_dir
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(0o700)
    digest = hashlib.sha256(str(job_id).encode()).hexdigest()
    return directory / f"managed-job-{digest}.lock"


class ManagedJobLease:
    """Hold one managed-job liveness lock in a dedicated native thread."""

    def __init__(self, job_id: str) -> None:
        self.job_id = str(job_id)
        self.path = managed_job_lease_path(self.job_id)
        self._acquired = threading.Event()
        self._release = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"managed-job-lease-{self.job_id}",
            daemon=True,
        )

    def _run(self) -> None:
        try:
            with private_file_lock(
                self.path,
                timeout_s=MANAGED_JOB_LEASE_ACQUIRE_TIMEOUT_S,
            ):
                self._acquired.set()
                self._release.wait()
        except BaseException as exc:
            self._error = exc
            self._acquired.set()

    def acquire(self) -> None:
        """Acquire the lease before the active durable row becomes visible."""
        self._thread.start()
        if not self._acquired.wait(MANAGED_JOB_LEASE_ACQUIRE_TIMEOUT_S + 1.0):
            self._release.set()
            self._thread.join(MANAGED_JOB_LEASE_JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                raise RuntimeError(
                    "managed job liveness lease acquisition timed out and the "
                    "lease thread did not exit"
                )
            raise RuntimeError(
                "managed job liveness lease acquisition timed out"
            )
        if self._error is not None:
            raise self._error
        if not self._thread.is_alive():
            raise RuntimeError(
                "managed job liveness lease exited before acquisition"
            )

    def release(self) -> None:
        """Release the lease after the terminal durable state is committed."""
        self._release.set()
        self._thread.join(MANAGED_JOB_LEASE_JOIN_TIMEOUT_S)
        if self._thread.is_alive():
            raise RuntimeError("managed job liveness lease did not exit")
        if self._error is not None:
            raise self._error


def managed_job_lease_state(
    job_id: str, lease_version: object
) -> ManagedJobLeaseState:
    """Classify one durable managed job from its cross-process lease."""
    if not str(job_id).strip():
        return "unknown"
    if lease_version != MANAGED_JOB_LEASE_VERSION:
        # Rows from releases before managed-job leases cannot have a live owner
        # in this runtime. Treat them as definitively stale so normal refresh
        # migrates them to the recoverable lost/stopped terminal path.
        return "dead"
    path = managed_job_lease_path(str(job_id))
    if not path.exists():
        return "unknown"
    try:
        with private_file_lock(path, timeout_s=0.0):
            return "dead"
    except TimeoutError:
        return "live"
    except OSError:
        return "unknown"
