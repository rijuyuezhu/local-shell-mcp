"""Secure remote-worker bundle installation and process replacement."""

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .. import __version__
from ..remote.constants import (
    REMOTE_WORKER_MANIFEST_PATH,
    REMOTE_WORKER_POLL_PROTOCOL_VERSION,
    REMOTE_WORKER_RUNTIME_KIND,
    REMOTE_WORKER_RUNTIME_PROTOCOL_VERSION,
)
from ..utils.private_files import private_file_lock
from .state import (
    runtime_metadata_path,
    worker_install_lock_path,
    worker_runtime_dir,
    worker_runtime_dir_for_digest,
    worker_runtimes_dir,
    worker_state_dir,
)

__all__ = ("worker_state_dir",)

POLL_PROTOCOL_VERSION = REMOTE_WORKER_POLL_PROTOCOL_VERSION
MANIFEST_SCHEMA_VERSION = 1
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_FILES = 4_096
_REQUIRED_RUNTIME_FILES = (
    "local_shell_mcp/__init__.py",
    "local_shell_mcp/remote_worker/__init__.py",
    "local_shell_mcp/remote_worker/__main__.py",
    "local_shell_mcp/remote_worker/compat.py",
    "local_shell_mcp/remote_worker/identity.py",
    "local_shell_mcp/remote_worker/lifecycle.py",
    "local_shell_mcp/remote_worker/migration.py",
    "local_shell_mcp/remote_worker/profile_launcher.py",
    "local_shell_mcp/remote_worker/profiles.py",
    "local_shell_mcp/remote_worker/state.py",
    "local_shell_mcp/remote_worker/worker.py",
)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_RELEASE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
_RUNTIME_MODULE_PATH = Path("local_shell_mcp/remote_worker/runtime.py")


def read_runtime_metadata(digest: str | None = None) -> dict[str, Any]:
    """Read valid runtime metadata, returning an empty object when absent."""
    try:
        decoded = json.loads(
            runtime_metadata_path(digest).read_text(encoding="utf-8")
        )
    except FileNotFoundError, OSError, ValueError, json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
        return {}
    digest = str(decoded.get("sha256") or "")
    version = str(decoded.get("bundle_version") or "")
    if not _DIGEST_RE.fullmatch(digest) or not version:
        return {}
    return decoded


def runtime_identity(digest: str | None = None) -> dict[str, str]:
    """Return one installed digest/version only for a complete runtime."""
    metadata = read_runtime_metadata(digest)
    runtime = worker_runtime_dir(digest)
    if not metadata or not all(
        (runtime / item).is_file() for item in _REQUIRED_RUNTIME_FILES
    ):
        return {"sha256": "", "bundle_version": ""}
    return {
        "sha256": str(metadata["sha256"]),
        "bundle_version": str(metadata["bundle_version"]),
    }


def current_runtime_identity() -> dict[str, str]:
    """Return identity only when this module executes from the selected runtime."""
    identity = runtime_identity()
    if not identity.get("sha256"):
        return identity
    selected_module = (worker_runtime_dir() / _RUNTIME_MODULE_PATH).resolve()
    try:
        executing_module = Path(__file__).resolve()
    except OSError:
        return {"sha256": "", "bundle_version": ""}
    if executing_module != selected_module:
        return {"sha256": "", "bundle_version": ""}
    return identity


def worker_poll_payload(
    worker_version: str,
    runtime_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the versioned poll payload understood by upgraded controllers."""
    identity = (
        current_runtime_identity()
        if runtime_identity is None
        else runtime_identity
    )
    return {
        "protocol_version": POLL_PROTOCOL_VERSION,
        "runtime_kind": (
            REMOTE_WORKER_RUNTIME_KIND
            if identity.get("sha256")
            else "unmanaged_source"
        ),
        "worker_version": worker_version,
        "bundle_sha256": str(identity.get("sha256") or ""),
        "bundle_version": str(identity.get("bundle_version") or ""),
    }


def worker_runtime_report(worker_version: str) -> dict[str, Any]:
    """Describe whether this process is running a verified managed bundle."""
    identity = current_runtime_identity()
    digest = str(identity.get("sha256") or "")
    bundle_version = str(identity.get("bundle_version") or "")
    return {
        "protocol_version": REMOTE_WORKER_RUNTIME_PROTOCOL_VERSION,
        "runtime_kind": REMOTE_WORKER_RUNTIME_KIND
        if digest
        else "unmanaged_source",
        "worker_version": worker_version,
        "bundle_version": bundle_version,
        "bundle_sha256": digest,
    }


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname or parsed.username:
        raise ValueError(
            "worker upgrade URL must use an absolute HTTP(S) origin"
        )
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def _same_origin(server: str, url: str) -> bool:
    return _origin(server) == _origin(url)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that leave the authenticated controller origin."""

    def __init__(self, server: str) -> None:
        super().__init__()
        self._server = server

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        if not _same_origin(self._server, resolved):
            raise ValueError(
                "worker upgrade redirect must remain on controller origin"
            )
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            resolved,
        )


def _fetch_bytes(
    url: str,
    *,
    server: str,
    timeout: float,
    max_bytes: int,
) -> bytes:
    """Fetch bounded bytes without cache reuse or cross-origin redirects."""
    if not _same_origin(server, url):
        raise ValueError("worker upgrade URL must remain on controller origin")
    request = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": f"local-shell-mcp-worker/{__version__}",
        },
    )
    opener = urllib.request.build_opener(_SameOriginRedirectHandler(server))
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        if not _same_origin(server, final_url):
            raise ValueError("worker upgrade response left controller origin")
        length_header = response.headers.get("Content-Length")
        if length_header:
            try:
                content_length = int(length_header)
            except ValueError as exc:
                raise ValueError(
                    "worker upgrade response has invalid size"
                ) from exc
            if content_length > max_bytes:
                raise ValueError("worker upgrade response exceeds size limit")
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("worker upgrade response exceeds size limit")
    return payload


def _manifest_url(server: str, manifest_path: str) -> str:
    parsed = urllib.parse.urlsplit(manifest_path)
    if parsed.scheme or parsed.netloc or not manifest_path.startswith("/"):
        raise ValueError(
            "worker upgrade manifest path must be controller-relative"
        )
    url = urllib.parse.urljoin(
        server.rstrip("/") + "/", manifest_path.lstrip("/")
    )
    if not _same_origin(server, url):
        raise ValueError(
            "worker upgrade manifest must remain on controller origin"
        )
    return url


def fetch_manifest(
    server: str,
    *,
    manifest_path: str,
    expected_version: str,
    expected_digest: str,
) -> dict[str, Any]:
    """Fetch and verify the controller manifest named by an authenticated poll."""
    manifest_url = _manifest_url(server, manifest_path)
    payload = _fetch_bytes(
        manifest_url,
        server=server,
        timeout=60,
        max_bytes=256 * 1024,
    )
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid remote worker manifest JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("invalid remote worker manifest")
    if decoded.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported remote worker manifest schema")

    digest = str(decoded.get("sha256") or "").lower()
    version = str(decoded.get("bundle_version") or "")
    bundle_url = str(decoded.get("url") or "")
    size = decoded.get("size")
    if not _DIGEST_RE.fullmatch(digest):
        raise ValueError("remote worker manifest has invalid digest")
    if (
        not version
        or len(version) > 128
        or any(ord(char) < 32 for char in version)
    ):
        raise ValueError("remote worker manifest has invalid version")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 < size <= MAX_BUNDLE_BYTES
    ):
        raise ValueError("remote worker manifest has invalid size")
    if digest != expected_digest or version != expected_version:
        raise ValueError(
            "remote worker manifest does not match poll instruction"
        )

    resolved_url = urllib.parse.urljoin(server.rstrip("/") + "/", bundle_url)
    if not _same_origin(server, resolved_url):
        raise ValueError(
            "remote worker bundle URL must remain on controller origin"
        )
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(resolved_url).query)
    if query.get("sha256") != [digest]:
        raise ValueError("remote worker bundle URL is not digest-qualified")
    decoded["url"] = resolved_url
    return decoded


def fetch_latest_manifest(server: str) -> dict[str, Any]:
    """Fetch the current manifest and revalidate it against a second stable read."""
    manifest_url = _manifest_url(server, REMOTE_WORKER_MANIFEST_PATH)
    payload = _fetch_bytes(
        manifest_url,
        server=server,
        timeout=60,
        max_bytes=256 * 1024,
    )
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid remote worker manifest JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("invalid remote worker manifest")
    version = str(decoded.get("bundle_version") or "")
    digest = str(decoded.get("sha256") or "").lower()
    if not version or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("remote worker manifest has invalid identity")
    return fetch_manifest(
        server,
        manifest_path=REMOTE_WORKER_MANIFEST_PATH,
        expected_version=version,
        expected_digest=digest,
    )


def _safe_member_target(destination: Path, name: str) -> Path:
    pure = PurePosixPath(name)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"unsafe worker bundle path: {name}")
    target = destination.joinpath(*pure.parts)
    destination_resolved = destination.resolve()
    target_resolved = target.resolve()
    if (
        target_resolved != destination_resolved
        and destination_resolved not in target_resolved.parents
    ):
        raise ValueError(f"unsafe worker bundle path: {name}")
    return target


def safe_extract_bundle(archive: Path, destination: Path) -> None:
    """Extract only bounded regular files and directories without links."""
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    total_size = 0
    file_count = 0
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar:
            normalized_name = member.name.rstrip("/")
            target = _safe_member_target(destination, normalized_name)
            if normalized_name in seen:
                raise ValueError(f"duplicate worker bundle path: {member.name}")
            seen.add(normalized_name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=False)
                with contextlib.suppress(OSError):
                    target.chmod(0o755)
                continue
            if not member.isreg():
                raise ValueError(
                    f"unsupported worker bundle member: {member.name}"
                )
            file_count += 1
            total_size += member.size
            if (
                file_count > MAX_ARCHIVE_FILES
                or total_size > MAX_EXTRACTED_BYTES
            ):
                raise ValueError(
                    "worker bundle extracted content exceeds limits"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError(f"duplicate worker bundle path: {member.name}")
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(
                    f"worker bundle file is unreadable: {member.name}"
                )
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            mode = 0o755 if member.mode & 0o111 else 0o644
            with contextlib.suppress(OSError):
                target.chmod(mode)

    missing = [
        item
        for item in _REQUIRED_RUNTIME_FILES
        if not (destination / item).is_file()
    ]
    if missing:
        raise ValueError(f"worker bundle is incomplete: missing {missing[0]}")


def _write_runtime_metadata(
    data: dict[str, Any], digest: str | None = None
) -> None:
    path = runtime_metadata_path(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _release_tuple(version: str) -> tuple[int, int, int] | None:
    match = _RELEASE_RE.match(version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _reject_downgrade(current_version: str, target_version: str) -> None:
    current = _release_tuple(current_version)
    target = _release_tuple(target_version)
    if current is not None and target is not None and target < current:
        raise ValueError(
            f"refusing worker runtime downgrade from {current_version} to {target_version}"
        )


def install_runtime(
    server: str,
    instruction: dict[str, Any],
    *,
    current_version: str,
    force: bool = False,
) -> dict[str, Any]:
    """Install one authenticated bundle instruction transactionally."""
    expected_digest = str(instruction.get("sha256") or "").lower()
    expected_version = str(instruction.get("version") or "")
    manifest_path = str(instruction.get("manifest_path") or "")
    if not _DIGEST_RE.fullmatch(expected_digest):
        raise ValueError("worker upgrade instruction has invalid digest")
    if not expected_version or len(expected_version) > 128:
        raise ValueError("worker upgrade instruction has invalid version")
    _reject_downgrade(current_version, expected_version)

    runtime = worker_runtime_dir_for_digest(expected_digest)
    runtimes = worker_runtimes_dir()
    runtimes.mkdir(parents=True, exist_ok=True)
    with private_file_lock(worker_install_lock_path()):
        current = runtime_identity(expected_digest)
        if (
            not force
            and current["sha256"] == expected_digest
            and runtime.is_dir()
        ):
            return {
                "updated": False,
                "sha256": expected_digest,
                "version": expected_version,
                "runtime": str(runtime),
            }

        manifest = fetch_manifest(
            server,
            manifest_path=manifest_path,
            expected_version=expected_version,
            expected_digest=expected_digest,
        )
        payload = _fetch_bytes(
            str(manifest["url"]),
            server=server,
            timeout=120,
            max_bytes=int(manifest["size"]),
        )
        if len(payload) != int(manifest["size"]):
            raise ValueError("worker bundle size does not match manifest")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(
                "worker bundle checksum does not match poll instruction"
            )

        backup = runtimes / f"{expected_digest}.previous.{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory(
            prefix=f"{expected_digest}.install-", dir=runtimes
        ) as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "worker.tgz"
            extracted = temporary_path / "runtime"
            archive.write_bytes(payload)
            safe_extract_bundle(archive, extracted)
            try:
                if runtime.exists():
                    os.replace(runtime, backup)
                os.replace(extracted, runtime)
                _write_runtime_metadata(
                    {
                        "schema_version": 1,
                        "bundle_version": expected_version,
                        "sha256": expected_digest,
                        "size": len(payload),
                        "installed_at": time.time(),
                    },
                    expected_digest,
                )
            except Exception:
                shutil.rmtree(runtime, ignore_errors=True)
                if backup.exists():
                    os.replace(backup, runtime)
                raise
            finally:
                shutil.rmtree(backup, ignore_errors=True)

    return {
        "updated": True,
        "sha256": expected_digest,
        "version": expected_version,
        "runtime": str(runtime),
    }


def reexec_environment() -> dict[str, str]:
    """Return an environment preferring the installed runtime exactly once."""
    runtime = worker_runtime_dir()
    preferred = [str(runtime)]
    inherited = [
        entry
        for entry in os.getenv("PYTHONPATH", "").split(os.pathsep)
        if entry
    ]
    entries: list[str] = []
    seen: set[str] = set()
    for entry in [*preferred, *inherited]:
        key = os.path.normcase(os.path.abspath(entry))
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


def worker_reexec_argv() -> list[str]:
    """Build a credential-free restart argv using only persisted identity."""
    return [
        sys.executable,
        "-m",
        "local_shell_mcp.remote_worker",
        "run",
    ]


def update_installed_runtime(
    server: str, *, force: bool = False
) -> dict[str, Any]:
    """Install the controller's latest verified worker bundle without restarting."""
    from ..version import version_info

    manifest = fetch_latest_manifest(server)
    current = current_runtime_identity()
    current_version = str(current.get("bundle_version") or "") or str(
        version_info().get("version") or ""
    )
    return install_runtime(
        server,
        {
            "version": str(manifest["bundle_version"]),
            "sha256": str(manifest["sha256"]),
            "manifest_path": REMOTE_WORKER_MANIFEST_PATH,
        },
        current_version=current_version,
        force=force,
    )


def reexec_worker() -> None:
    """Replace the worker while preserving its single-instance lock."""
    from .lifecycle import (
        cancel_worker_lock_reexec,
        prepare_worker_lock_reexec,
    )

    argv = worker_reexec_argv()
    inherited = prepare_worker_lock_reexec()
    try:
        environment = reexec_environment()
        if sys.platform == "win32":
            subprocess.Popen(  # noqa: S603
                argv,
                env=environment,
                close_fds=False,
            )
            raise SystemExit(0)
        os.execve(argv[0], argv, environment)
    finally:
        cancel_worker_lock_reexec(inherited)
