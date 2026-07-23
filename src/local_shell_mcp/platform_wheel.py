"""Build and verify platform wheels containing the native OpenTUI runtime.

The ordinary project build remains a pure ``py3-none-any`` wheel.  This module
is used only by release tooling: it stages one deterministic compressed native
payload, delegates the initial wheel build to ``uv_build``, rewrites the wheel
metadata with an explicit platform tag, regenerates ``RECORD``, and verifies the
finished artifact before it can be published.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile, ZipInfo

from packaging.tags import Tag
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from wheel.wheelfile import WheelError, WheelFile

BUN_VERSION = "1.3.14"
MAX_EXECUTABLE_BYTES = 256 * 1024 * 1024
MAX_COMPRESSED_BYTES = 192 * 1024 * 1024
PAYLOAD_PACKAGE_PREFIX = "local_shell_mcp/ui_runtime/"
_LOCK_NAME = ".platform-wheel-build.lock"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_COMPRESSION_CHUNK_BYTES = 1024 * 1024
_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"


class PlatformWheelError(RuntimeError):
    """Stable failure raised for unsafe or malformed platform-wheel builds."""


class _DeterministicWheelFile(WheelFile):
    """Write wheel members and ``RECORD`` with stable ZIP metadata."""

    def close(self) -> None:
        if self.fp is not None and self.mode == "w" and self._file_hashes:
            record = StringIO()
            writer = csv.writer(
                record,
                delimiter=",",
                quotechar='"',
                lineterminator="\n",
            )
            writer.writerows(
                (
                    (name, f"{algorithm}={digest}", self._file_sizes[name])
                    for name, (algorithm, digest) in self._file_hashes.items()
                )
            )
            writer.writerow((format(self.record_path), "", ""))
            info = ZipInfo(self.record_path, date_time=_ZIP_TIMESTAMP)
            info.compress_type = self.compression
            info.external_attr = (0o664 | stat.S_IFREG) << 16
            self.writestr(info, record.getvalue())
        ZipFile.close(self)


def _normalise_zip_info(info: ZipInfo) -> ZipInfo:
    info.date_time = _ZIP_TIMESTAMP
    info.extra = b""
    info.comment = b""
    return info


def _platform_wheel_lock_path(repo_root: Path) -> Path:
    repo_key = hashlib.sha256(
        os.fsencode(str(repo_root.resolve()))
    ).hexdigest()[:24]
    return (
        Path(tempfile.gettempdir()) / f"local-shell-mcp-wheel-{repo_key}.lock"
    )


@dataclass(frozen=True, slots=True)
class PlatformWheelTarget:
    """One explicit native wheel target and its executable contract."""

    tag: str
    """Explicit platform component used in the wheel tag."""
    system: str
    """Native ``platform.system()`` value required from the build host."""
    architecture: str
    """Normalized native architecture required from the build host."""
    executable_name: str
    """Filename used for the compiled and materialized OpenTUI executable."""
    executable_magics: tuple[bytes, ...]
    """Accepted leading file signatures for the target executable format."""

    @property
    def payload_path(self) -> str:
        """Return the package-relative compressed payload path."""

        return f"{PAYLOAD_PACKAGE_PREFIX}{self.executable_name}.gz"


@dataclass(frozen=True, slots=True)
class WheelInspection:
    """Verified metadata and payload digests for one wheel artifact."""

    path: str
    """Filesystem path of the inspected wheel artifact."""
    platform_tag: str
    """Verified platform component from the filename and ``WHEEL`` metadata."""
    root_is_purelib: bool
    """Whether ``WHEEL`` declares the artifact as a purelib wheel."""
    payload_path: str | None
    """Package-relative compressed payload member, when present."""
    payload_sha256: str | None
    """SHA-256 digest of the compressed payload, when present."""
    executable_sha256: str | None
    """SHA-256 digest of the decompressed native executable, when present."""
    compressed_size: int | None
    """Compressed payload size in bytes, when present."""
    executable_size: int | None
    """Decompressed native executable size in bytes, when present."""


_TARGETS = {
    "linux_x86_64": PlatformWheelTarget(
        tag="linux_x86_64",
        system="Linux",
        architecture="x86_64",
        executable_name="local-shell-mcp-tui",
        executable_magics=(b"\x7fELF",),
    ),
    "linux_aarch64": PlatformWheelTarget(
        tag="linux_aarch64",
        system="Linux",
        architecture="aarch64",
        executable_name="local-shell-mcp-tui",
        executable_magics=(b"\x7fELF",),
    ),
    "macosx_10_15_x86_64": PlatformWheelTarget(
        tag="macosx_10_15_x86_64",
        system="Darwin",
        architecture="x86_64",
        executable_name="local-shell-mcp-tui",
        executable_magics=(
            b"\xfe\xed\xfa\xce",
            b"\xfe\xed\xfa\xcf",
            b"\xce\xfa\xed\xfe",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        ),
    ),
    "macosx_11_0_arm64": PlatformWheelTarget(
        tag="macosx_11_0_arm64",
        system="Darwin",
        architecture="aarch64",
        executable_name="local-shell-mcp-tui",
        executable_magics=(
            b"\xfe\xed\xfa\xce",
            b"\xfe\xed\xfa\xcf",
            b"\xce\xfa\xed\xfe",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        ),
    ),
    "win_amd64": PlatformWheelTarget(
        tag="win_amd64",
        system="Windows",
        architecture="x86_64",
        executable_name="local-shell-mcp-tui.exe",
        executable_magics=(b"MZ",),
    ),
    "win_arm64": PlatformWheelTarget(
        tag="win_arm64",
        system="Windows",
        architecture="aarch64",
        executable_name="local-shell-mcp-tui.exe",
        executable_magics=(b"MZ",),
    ),
}


def target_for_tag(platform_tag: str) -> PlatformWheelTarget:
    """Return a supported explicit target or reject ambiguous/unsafe tags."""

    try:
        target = _TARGETS[platform_tag]
    except KeyError as exc:
        raise PlatformWheelError(
            f"unsupported platform wheel tag: {platform_tag!r}"
        ) from exc
    parsed = frozenset(_parse_tag_set(f"py3-none-{platform_tag}"))
    if parsed != {Tag("py3", "none", platform_tag)}:
        raise PlatformWheelError(
            f"invalid platform wheel tag: {platform_tag!r}"
        )
    return target


def _parse_tag_set(tag_text: str) -> frozenset[Tag]:
    from packaging.tags import parse_tag

    try:
        return parse_tag(tag_text)
    except ValueError as exc:
        raise PlatformWheelError(f"invalid wheel tag: {tag_text!r}") from exc


def _normalise_architecture(machine: str) -> str:
    normalized = machine.strip().lower().replace("-", "_")
    if normalized in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "aarch64"
    return normalized


def verify_target_host(
    target: PlatformWheelTarget,
    *,
    system_name: str | None = None,
    machine: str | None = None,
) -> None:
    """Require a native runner matching the declared target tag."""

    actual_system = system_name or platform.system()
    actual_architecture = _normalise_architecture(machine or platform.machine())
    if (
        actual_system != target.system
        or actual_architecture != target.architecture
    ):
        raise PlatformWheelError(
            "platform wheel target does not match the native build host: "
            f"target={target.system}/{target.architecture}, "
            f"host={actual_system}/{actual_architecture}"
        )


def deterministic_gzip(data: bytes) -> bytes:
    """Compress executable bytes into a bounded, cross-platform-stable gzip."""

    _verify_executable_size(data)
    output = bytearray(_GZIP_HEADER)
    if len(output) + 8 > MAX_COMPRESSED_BYTES:
        raise PlatformWheelError(
            "compressed OpenTUI payload exceeds the platform-wheel limit"
        )
    compressor = zlib.compressobj(
        level=9,
        method=zlib.DEFLATED,
        wbits=-zlib.MAX_WBITS,
    )
    checksum = 0
    view = memoryview(data)
    for offset in range(0, len(view), _COMPRESSION_CHUNK_BYTES):
        chunk = view[offset : offset + _COMPRESSION_CHUNK_BYTES]
        checksum = zlib.crc32(chunk, checksum)
        output.extend(compressor.compress(chunk))
        if len(output) + 8 > MAX_COMPRESSED_BYTES:
            raise PlatformWheelError(
                "compressed OpenTUI payload exceeds the platform-wheel limit"
            )
    output.extend(compressor.flush())
    output.extend(
        struct.pack("<II", checksum & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)
    )
    if len(output) > MAX_COMPRESSED_BYTES:
        raise PlatformWheelError(
            "compressed OpenTUI payload exceeds the platform-wheel limit"
        )
    result = bytes(output)
    if _decompress_payload(result) != data:
        raise PlatformWheelError(
            "compressed OpenTUI payload round-trip mismatch"
        )
    return result


def verify_executable(
    data: bytes,
    target: PlatformWheelTarget,
) -> str:
    """Verify executable bounds and native file magic, then return SHA-256."""

    _verify_executable_size(data)
    if not any(data.startswith(magic) for magic in target.executable_magics):
        raise PlatformWheelError(
            f"OpenTUI executable does not match {target.tag} file magic"
        )
    return hashlib.sha256(data).hexdigest()


def _verify_executable_size(data: bytes) -> None:
    if not data:
        raise PlatformWheelError("OpenTUI executable is empty")
    if len(data) > MAX_EXECUTABLE_BYTES:
        raise PlatformWheelError(
            "OpenTUI executable exceeds the wheel size limit"
        )


def _read_regular_file(path: Path, *, limit: int) -> bytes:
    if path.is_symlink():
        raise PlatformWheelError(f"refusing symlink build input: {path}")
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise PlatformWheelError(f"missing build input: {path}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise PlatformWheelError(f"build input is not a regular file: {path}")
    if file_stat.st_size > limit:
        raise PlatformWheelError(f"build input exceeds size limit: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PlatformWheelError(f"could not read build input: {path}") from exc
    if len(data) != file_stat.st_size:
        raise PlatformWheelError(f"build input changed while reading: {path}")
    return data


def _run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise PlatformWheelError(
            f"build command is unavailable: {command[0]}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if len(detail) > 2000:
            detail = detail[-2000:]
        suffix = f": {detail}" if detail else ""
        raise PlatformWheelError(
            f"build command failed ({command[0]}){suffix}"
        ) from exc


def compile_opentui(
    repo_root: Path,
    target: PlatformWheelTarget,
    *,
    bun_executable: str = "bun",
) -> bytes:
    """Compile OpenTUI on a matching host using the pinned Bun release."""

    verify_target_host(target)
    version = _run_checked([bun_executable, "--version"], cwd=repo_root)
    if version.stdout.strip() != BUN_VERSION:
        raise PlatformWheelError(
            f"Bun {BUN_VERSION} is required, found {version.stdout.strip()!r}"
        )
    ui_root = repo_root / "ui-opentui"
    if not (ui_root / "bun.lock").is_file():
        raise PlatformWheelError("ui-opentui/bun.lock is missing")
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-opentui-") as temp:
        binary_dir = Path(temp) / "binary"
        env = os.environ.copy()
        env["LSM_UI_BINARY_OUTDIR"] = str(binary_dir)
        env.pop("LSM_UI_EMBED_RUNTIME", None)
        _run_checked(
            [bun_executable, "run", "build:tui"],
            cwd=ui_root,
            env=env,
        )
        executable = binary_dir / target.executable_name
        data = _read_regular_file(executable, limit=MAX_EXECUTABLE_BYTES)
        verify_executable(data, target)
        return data


def _safe_remove_staging(staging: Path) -> None:
    if not staging.exists() and not staging.is_symlink():
        return
    if staging.is_symlink():
        raise PlatformWheelError(f"refusing symlink staging path: {staging}")
    if not staging.is_dir():
        raise PlatformWheelError(f"staging path is not a directory: {staging}")
    shutil.rmtree(staging)


@contextmanager
def staged_payload(
    repo_root: Path,
    target: PlatformWheelTarget,
    payload: bytes,
    *,
    lock_timeout: float = 30.0,
) -> Generator[Path]:
    """Stage one payload under an exclusive cross-platform build lock."""

    if lock_timeout < 0:
        raise PlatformWheelError("lock timeout must be non-negative")
    package_root = repo_root / "src" / "local_shell_mcp"
    if not package_root.is_dir():
        raise PlatformWheelError("local_shell_mcp package directory is missing")
    lock_path = _platform_wheel_lock_path(repo_root)
    staging = package_root / "ui_runtime"
    deadline = time.monotonic() + lock_timeout
    lock_fd: int | None = None
    while lock_fd is None:
        try:
            lock_fd = os.open(
                lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError as exc:
            if lock_path.is_symlink():
                raise PlatformWheelError(
                    f"refusing symlink platform-wheel lock: {lock_path}"
                ) from exc
            if time.monotonic() >= deadline:
                raise PlatformWheelError(
                    "timed out waiting for platform-wheel lock"
                ) from exc
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        except OSError as exc:
            raise PlatformWheelError(
                "could not create platform-wheel lock"
            ) from exc
    created_staging = False
    try:
        os.write(lock_fd, f"pid={os.getpid()}\n".encode())
        os.fsync(lock_fd)
        _safe_remove_staging(staging)
        staging.mkdir(mode=0o755)
        created_staging = True
        payload_path = staging / f"{target.executable_name}.gz"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(payload_path, flags, 0o644)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise PlatformWheelError(
                        "could not write staged OpenTUI payload"
                    )
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        yield payload_path
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        cleanup_error: PlatformWheelError | None = None
        if created_staging:
            try:
                _safe_remove_staging(staging)
            except PlatformWheelError as exc:
                cleanup_error = exc
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as exc:
            if cleanup_error is None:
                cleanup_error = PlatformWheelError(
                    "could not remove platform-wheel lock"
                )
                cleanup_error.__cause__ = exc
        if cleanup_error is not None:
            raise cleanup_error


def _wheel_members(path: Path) -> tuple[list[tuple[ZipInfo, bytes]], str, str]:
    try:
        with WheelFile(path, "r") as wheel_file:
            names = wheel_file.namelist()
            wheel_paths = [
                name for name in names if name.endswith(".dist-info/WHEEL")
            ]
            record_paths = [
                name for name in names if name.endswith(".dist-info/RECORD")
            ]
            if len(wheel_paths) != 1 or len(record_paths) != 1:
                raise PlatformWheelError(
                    "wheel must contain exactly one WHEEL and one RECORD"
                )
            members = [
                (info, wheel_file.read(info.filename))
                for info in wheel_file.infolist()
                if info.filename != record_paths[0]
            ]
            return members, wheel_paths[0], record_paths[0]
    except (BadZipFile, WheelError, KeyError, RuntimeError) as exc:
        if isinstance(exc, PlatformWheelError):
            raise
        raise PlatformWheelError(f"invalid wheel archive: {path}") from exc


def _parse_wheel_tags(path: Path) -> frozenset[Tag]:
    try:
        _name, _version, _build, tags = parse_wheel_filename(path.name)
    except InvalidWheelFilename as exc:
        raise PlatformWheelError(
            f"invalid wheel filename: {path.name}"
        ) from exc
    return frozenset(tags)


def _wheel_metadata(data: bytes) -> tuple[bool, frozenset[Tag]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlatformWheelError("WHEEL metadata is not UTF-8") from exc
    pure_values = [
        line.split(":", 1)[1].strip().lower()
        for line in text.splitlines()
        if line.lower().startswith("root-is-purelib:")
    ]
    tag_values = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().startswith("tag:")
    ]
    if len(pure_values) != 1 or pure_values[0] not in {"true", "false"}:
        raise PlatformWheelError("WHEEL must contain one valid Root-Is-Purelib")
    if not tag_values:
        raise PlatformWheelError("WHEEL metadata has no Tag")
    tags: set[Tag] = set()
    for value in tag_values:
        tags.update(_parse_tag_set(value))
    return pure_values[0] == "true", frozenset(tags)


def _rewrite_wheel_metadata(data: bytes, target: PlatformWheelTarget) -> bytes:
    pure, tags = _wheel_metadata(data)
    if not pure or tags != {Tag("py3", "none", "any")}:
        raise PlatformWheelError(
            "input wheel must be the unmodified py3-none-any uv_build artifact"
        )
    text = data.decode("utf-8")
    lines = []
    for line in text.splitlines():
        lower = line.lower()
        if lower.startswith("root-is-purelib:"):
            lines.append("Root-Is-Purelib: false")
        elif lower.startswith("tag:"):
            lines.append(f"Tag: py3-none-{target.tag}")
        else:
            lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def _decompress_payload(payload: bytes) -> bytes:
    if not payload:
        raise PlatformWheelError("embedded OpenTUI payload is empty")
    if len(payload) > MAX_COMPRESSED_BYTES:
        raise PlatformWheelError(
            "embedded OpenTUI gzip exceeds the wheel limit"
        )
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as source:
            while True:
                chunk = source.read(
                    min(_COMPRESSION_CHUNK_BYTES, MAX_EXECUTABLE_BYTES + 1)
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > MAX_EXECUTABLE_BYTES:
                    raise PlatformWheelError(
                        "embedded OpenTUI executable exceeds the wheel limit"
                    )
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as exc:
        raise PlatformWheelError(
            "embedded OpenTUI payload is not valid gzip"
        ) from exc
    return bytes(output)


def inspect_wheel(
    path: Path,
    *,
    target: PlatformWheelTarget | None,
) -> WheelInspection:
    """Verify a universal wheel or one exact platform wheel."""

    filename_tags = _parse_wheel_tags(path)
    members, wheel_path, _record_path = _wheel_members(path)
    member_map = {info.filename: data for info, data in members}
    if any(
        not name.endswith("/") and name.rsplit("/", 1)[-1] == _LOCK_NAME
        for name in member_map
    ):
        raise PlatformWheelError("wheel contains the platform-wheel build lock")
    pure, metadata_tags = _wheel_metadata(member_map[wheel_path])
    if filename_tags != metadata_tags:
        raise PlatformWheelError("wheel filename and WHEEL tags disagree")
    payload_paths = sorted(
        name
        for name in member_map
        if name.startswith(PAYLOAD_PACKAGE_PREFIX) and not name.endswith("/")
    )
    if target is None:
        expected_tags = {Tag("py3", "none", "any")}
        if filename_tags != expected_tags or not pure:
            raise PlatformWheelError(
                "universal wheel must be pure py3-none-any"
            )
        if payload_paths:
            raise PlatformWheelError(
                "universal wheel must not contain native payloads"
            )
        return WheelInspection(
            path=str(path),
            platform_tag="any",
            root_is_purelib=True,
            payload_path=None,
            payload_sha256=None,
            executable_sha256=None,
            compressed_size=None,
            executable_size=None,
        )
    expected_tags = {Tag("py3", "none", target.tag)}
    if filename_tags != expected_tags or pure:
        raise PlatformWheelError(
            f"platform wheel must be non-pure py3-none-{target.tag}"
        )
    if payload_paths != [target.payload_path]:
        raise PlatformWheelError(
            "platform wheel must contain exactly the expected OpenTUI payload"
        )
    payload = member_map[target.payload_path]
    executable = _decompress_payload(payload)
    executable_sha256 = verify_executable(executable, target)
    return WheelInspection(
        path=str(path),
        platform_tag=target.tag,
        root_is_purelib=False,
        payload_path=target.payload_path,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        executable_sha256=executable_sha256,
        compressed_size=len(payload),
        executable_size=len(executable),
    )


def inspect_sdist(path: Path) -> None:
    """Require a source-only sdist with no native/generated OpenTUI artifacts."""

    forbidden_parts = {"node_modules", "dist", "coverage"}
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if PAYLOAD_PACKAGE_PREFIX.rstrip("/") in "/".join(parts):
                    raise PlatformWheelError(
                        "sdist contains embedded OpenTUI payload"
                    )
                if "ui-opentui" in parts and forbidden_parts.intersection(
                    parts
                ):
                    raise PlatformWheelError(
                        "sdist contains generated OpenTUI files"
                    )
    except (tarfile.TarError, OSError) as exc:
        if isinstance(exc, PlatformWheelError):
            raise
        raise PlatformWheelError(f"invalid sdist archive: {path}") from exc


def rewrite_platform_wheel(
    universal_wheel: Path,
    output_dir: Path,
    target: PlatformWheelTarget,
    *,
    expected_payload_sha256: str,
    expected_executable_sha256: str,
) -> tuple[Path, WheelInspection]:
    """Rewrite a staged universal wheel into one verified platform wheel."""

    if _parse_wheel_tags(universal_wheel) != {Tag("py3", "none", "any")}:
        raise PlatformWheelError("input filename must use py3-none-any")
    members, wheel_path, _record_path = _wheel_members(universal_wheel)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-py3-none-any.whl"
    if not universal_wheel.name.endswith(suffix):
        raise PlatformWheelError(
            "input wheel filename has an unexpected tag suffix"
        )
    output_name = (
        f"{universal_wheel.name.removesuffix(suffix)}-py3-none-{target.tag}.whl"
    )
    output_path = output_dir / output_name
    if output_path.exists():
        raise PlatformWheelError(f"output wheel already exists: {output_path}")
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=".platform-wheel-", dir=output_dir)
    )
    temporary_path = temporary_dir / output_name
    try:
        with _DeterministicWheelFile(temporary_path, "w") as output:
            for info, data in members:
                if info.filename == wheel_path:
                    data = _rewrite_wheel_metadata(data, target)
                output.writestr(_normalise_zip_info(info), data)
        os.replace(temporary_path, output_path)
        inspection = inspect_wheel(output_path, target=target)
        if inspection.payload_sha256 != expected_payload_sha256:
            raise PlatformWheelError("platform wheel payload digest changed")
        if inspection.executable_sha256 != expected_executable_sha256:
            raise PlatformWheelError("platform wheel executable digest changed")
        return output_path, inspection
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def _build_staged_universal_wheel(
    repo_root: Path,
    build_dir: Path,
    *,
    uv_executable: str,
) -> Path:
    _run_checked(
        [uv_executable, "build", "--wheel", "--out-dir", str(build_dir)],
        cwd=repo_root,
    )
    wheels = sorted(build_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise PlatformWheelError(
            f"uv build produced {len(wheels)} wheels; expected exactly one"
        )
    return wheels[0]


def build_platform_wheel(
    repo_root: Path,
    output_dir: Path,
    target: PlatformWheelTarget,
    *,
    bun_executable: str = "bun",
    uv_executable: str = "uv",
    lock_timeout: float = 30.0,
) -> tuple[Path, WheelInspection]:
    """Compile, stage, build, rewrite, verify, and clean one platform wheel."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    executable = compile_opentui(
        repo_root,
        target,
        bun_executable=bun_executable,
    )
    executable_sha256 = verify_executable(executable, target)
    payload = deterministic_gzip(executable)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-wheel-") as temp:
        build_dir = Path(temp) / "build"
        build_dir.mkdir()
        with staged_payload(
            repo_root,
            target,
            payload,
            lock_timeout=lock_timeout,
        ):
            universal = _build_staged_universal_wheel(
                repo_root,
                build_dir,
                uv_executable=uv_executable,
            )
            return rewrite_platform_wheel(
                universal,
                output_dir,
                target,
                expected_payload_sha256=payload_sha256,
                expected_executable_sha256=executable_sha256,
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a verified local-shell-mcp wheel with embedded OpenTUI",
    )
    parser.add_argument(
        "--platform-tag", required=True, choices=sorted(_TARGETS)
    )
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--bun", default="bun")
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--lock-timeout", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the repository platform-wheel build script."""

    args = _parser().parse_args(argv)
    try:
        path, inspection = build_platform_wheel(
            args.repo_root,
            args.output_dir,
            target_for_tag(args.platform_tag),
            bun_executable=args.bun,
            uv_executable=args.uv,
            lock_timeout=args.lock_timeout,
        )
    except PlatformWheelError as exc:
        print(f"platform wheel build failed: {exc}", file=sys.stderr)
        return 1
    result = asdict(inspection)
    result["path"] = str(path)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
