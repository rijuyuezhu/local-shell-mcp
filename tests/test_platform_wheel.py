import gzip
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import zlib
from pathlib import Path
from zipfile import ZIP_STORED

import pytest
from wheel.wheelfile import WheelFile

from local_shell_mcp.release import platform_wheel as pw
from local_shell_mcp.ui.contracts import (
    POSIX_TUI_EXECUTABLE_NAME,
    WINDOWS_TUI_EXECUTABLE_NAME,
)


def _executable(
    target: pw.PlatformWheelTarget, body: bytes = b"runtime"
) -> bytes:
    return target.executable_magics[0] + body


def _make_wheel(
    path: Path,
    *,
    wheel_metadata: bytes | None = None,
    payloads: dict[str, bytes] | None = None,
) -> Path:
    dist_info = "local_shell_mcp-1.0.dist-info"
    metadata = wheel_metadata or (
        b"Wheel-Version: 1.0\n"
        b"Generator: test\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )
    with WheelFile(path, "w") as wheel:
        wheel.writestr("local_shell_mcp/__init__.py", b"")
        wheel.writestr(
            f"{dist_info}/METADATA",
            b"Metadata-Version: 2.4\nName: local-shell-mcp\nVersion: 1.0\n",
        )
        wheel.writestr(f"{dist_info}/WHEEL", metadata)
        if payloads:
            wheel.writestr("local_shell_mcp/ui_runtime/", b"")
        for name, data in (payloads or {}).items():
            wheel.writestr(name, data)
    return path


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "local_shell_mcp").mkdir(parents=True)
    (repo / "ui-opentui").mkdir()
    (repo / "ui-opentui" / "bun.lock").write_text("lock", encoding="utf-8")
    return repo


@pytest.mark.parametrize(
    ("tag", "system", "architecture", "executable"),
    [
        ("linux_x86_64", "Linux", "x86_64", POSIX_TUI_EXECUTABLE_NAME),
        ("linux_aarch64", "Linux", "aarch64", POSIX_TUI_EXECUTABLE_NAME),
        ("macosx_10_15_x86_64", "Darwin", "x86_64", POSIX_TUI_EXECUTABLE_NAME),
        ("macosx_11_0_arm64", "Darwin", "aarch64", POSIX_TUI_EXECUTABLE_NAME),
        ("win_amd64", "Windows", "x86_64", WINDOWS_TUI_EXECUTABLE_NAME),
        ("win_arm64", "Windows", "aarch64", WINDOWS_TUI_EXECUTABLE_NAME),
    ],
)
def test_target_for_tag(
    tag: str,
    system: str,
    architecture: str,
    executable: str,
) -> None:
    target = pw.target_for_tag(tag)
    assert target.system == system
    assert target.architecture == architecture
    assert target.executable_name == executable
    assert target.payload_path == f"local_shell_mcp/ui_runtime/{executable}.gz"


@pytest.mark.parametrize("tag", ["", "manylinux_2_17_x86_64", "win32", "any"])
def test_target_for_tag_rejects_unapproved_tags(tag: str) -> None:
    with pytest.raises(pw.PlatformWheelError, match="unsupported"):
        pw.target_for_tag(tag)


def test_parse_tag_rejects_invalid_value() -> None:
    with pytest.raises(pw.PlatformWheelError, match="invalid wheel tag"):
        pw._parse_tag_set("not a tag!")


@pytest.mark.parametrize("machine", ["x86_64", "AMD64", "x64", "x86-64"])
def test_verify_target_host_normalises_x86(machine: str) -> None:
    pw.verify_target_host(
        pw.target_for_tag("linux_x86_64"),
        system_name="Linux",
        machine=machine,
    )


@pytest.mark.parametrize("machine", ["aarch64", "ARM64"])
def test_verify_target_host_normalises_arm(machine: str) -> None:
    pw.verify_target_host(
        pw.target_for_tag("linux_aarch64"),
        system_name="Linux",
        machine=machine,
    )


def test_verify_target_host_rejects_cross_tag() -> None:
    with pytest.raises(pw.PlatformWheelError, match="does not match"):
        pw.verify_target_host(
            pw.target_for_tag("win_arm64"),
            system_name="Windows",
            machine="AMD64",
        )


def test_deterministic_gzip_has_fixed_header_and_round_trips() -> None:
    data = b"\x7fELF" + b"x" * 1024
    first = pw.deterministic_gzip(data)
    second = pw.deterministic_gzip(data)
    assert first == second
    assert first[:10] == pw._GZIP_HEADER
    assert first[4:8] == b"\0\0\0\0"
    assert first[9] == 255
    assert gzip.decompress(first) == data


def test_deterministic_gzip_streams_multiple_members() -> None:
    pattern = bytes(range(256))
    data = b"MZ" + pattern * ((pw._COMPRESSION_CHUNK_BYTES * 2) // 256 + 1)
    payload = pw.deterministic_gzip(data)
    expected = b"".join(
        pw._deterministic_gzip_member(
            data[offset : offset + pw._COMPRESSION_CHUNK_BYTES]
        )
        for offset in range(0, len(data), pw._COMPRESSION_CHUNK_BYTES)
    )
    assert payload == expected
    assert gzip.decompress(payload) == data


def test_deterministic_gzip_rejects_round_trip_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pw, "_decompress_payload", lambda _payload: b"mismatch")
    with pytest.raises(pw.PlatformWheelError, match="round-trip mismatch"):
        pw.deterministic_gzip(b"MZruntime")


def test_deterministic_gzip_wraps_immediate_round_trip_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_payload: bytes) -> bytes:
        raise pw.PlatformWheelError("invalid gzip")

    monkeypatch.setattr(pw, "_decompress_payload", fail)
    with pytest.raises(pw.PlatformWheelError, match="failed immediate"):
        pw.deterministic_gzip(b"MZruntime")


@pytest.mark.parametrize("data", [b"", b"12345"])
def test_deterministic_gzip_enforces_raw_limit(
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
) -> None:
    monkeypatch.setattr(pw, "MAX_EXECUTABLE_BYTES", 4)
    with pytest.raises(pw.PlatformWheelError, match="empty|exceeds"):
        pw.deterministic_gzip(data)


def test_deterministic_gzip_enforces_compressed_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pw, "MAX_COMPRESSED_BYTES", 1)
    with pytest.raises(pw.PlatformWheelError, match="compressed"):
        pw.deterministic_gzip(b"1234")


@pytest.mark.parametrize(
    "tag",
    [
        "linux_x86_64",
        "linux_aarch64",
        "macosx_10_15_x86_64",
        "macosx_11_0_arm64",
        "win_amd64",
        "win_arm64",
    ],
)
def test_verify_executable_accepts_native_magic(tag: str) -> None:
    target = pw.target_for_tag(tag)
    data = _executable(target)
    assert (
        pw.verify_executable(data, target) == hashlib.sha256(data).hexdigest()
    )


def test_verify_executable_rejects_wrong_magic() -> None:
    with pytest.raises(pw.PlatformWheelError, match="file magic"):
        pw.verify_executable(b"not-native", pw.target_for_tag("linux_x86_64"))


def test_read_regular_file_rejects_missing_directory_and_symlink(
    tmp_path: Path,
) -> None:
    with pytest.raises(pw.PlatformWheelError, match="missing"):
        pw._read_regular_file(tmp_path / "missing", limit=100)
    with pytest.raises(pw.PlatformWheelError, match="not a regular"):
        pw._read_regular_file(tmp_path, limit=100)
    target = tmp_path / "target"
    target.write_bytes(b"x")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(pw.PlatformWheelError, match="symlink"):
        pw._read_regular_file(link, limit=100)


def test_read_regular_file_rejects_size(tmp_path: Path) -> None:
    path = tmp_path / "large"
    path.write_bytes(b"123")
    with pytest.raises(pw.PlatformWheelError, match="size limit"):
        pw._read_regular_file(path, limit=2)


def test_run_checked_reports_missing_and_failed_commands(
    tmp_path: Path,
) -> None:
    with pytest.raises(pw.PlatformWheelError, match="unavailable"):
        pw._run_checked([str(tmp_path / "missing")], cwd=tmp_path)
    with pytest.raises(pw.PlatformWheelError, match="failed.*boom"):
        pw._run_checked(
            [
                os.fspath(Path(sys.executable)),
                "-c",
                "import sys; print('boom', file=sys.stderr); raise SystemExit(3)",
            ],
            cwd=tmp_path,
        )


def test_compile_opentui_uses_pinned_bun_and_isolated_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    def fake_run(
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(command), cwd, env))
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                command, 0, f"{pw.BUN_VERSION}\n", ""
            )
        assert env is not None
        assert "LSM_UI_EMBED_RUNTIME" not in env
        output = Path(env["LSM_UI_BINARY_OUTDIR"])
        output.mkdir(parents=True)
        (output / target.executable_name).write_bytes(_executable(target))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(pw, "verify_target_host", lambda _target: None)
    monkeypatch.setattr(pw, "_run_checked", fake_run)
    assert pw.compile_opentui(
        repo, target, bun_executable="pinned-bun"
    ) == _executable(target)
    assert calls[0][0] == ["pinned-bun", "--version"]
    assert calls[1][0] == ["pinned-bun", "run", "build:tui"]
    assert calls[1][1] == repo / "ui-opentui"


def test_compile_opentui_rejects_wrong_bun_and_missing_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    monkeypatch.setattr(pw, "verify_target_host", lambda _target: None)
    monkeypatch.setattr(
        pw,
        "_run_checked",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, "0.0.0\n", ""
        ),
    )
    with pytest.raises(pw.PlatformWheelError, match="Bun"):
        pw.compile_opentui(repo, target)
    (repo / "ui-opentui" / "bun.lock").unlink()
    monkeypatch.setattr(
        pw,
        "_run_checked",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, f"{pw.BUN_VERSION}\n", ""
        ),
    )
    with pytest.raises(pw.PlatformWheelError, match="bun.lock"):
        pw.compile_opentui(repo, target)


def test_staged_payload_is_private_and_always_cleaned(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    payload = pw.deterministic_gzip(_executable(target))
    package_root = repo / "src" / "local_shell_mcp"
    lock = pw._platform_wheel_lock_path(repo)
    with (
        pytest.raises(RuntimeError, match="stop"),
        pw.staged_payload(repo, target, payload) as path,
    ):
        assert path.read_bytes() == payload
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o644
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o755
            assert stat.S_IMODE(lock.stat().st_mode) == 0o600
        raise RuntimeError("stop")
    assert not (package_root / "ui_runtime").exists()
    assert not lock.exists()
    assert not (package_root / pw._LOCK_NAME).exists()


def test_staged_payload_cleans_stale_directory(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    stale = repo / "src" / "local_shell_mcp" / "ui_runtime"
    stale.mkdir()
    (stale / "stale").write_text("old", encoding="utf-8")
    with pw.staged_payload(repo, target, b"payload") as path:
        assert path.read_bytes() == b"payload"
        assert not (stale / "stale").exists()
    assert not stale.exists()


def test_staged_payload_rejects_timeout_and_bad_paths(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    lock = pw._platform_wheel_lock_path(repo)
    lock.write_text("held", encoding="utf-8")
    with (
        pytest.raises(pw.PlatformWheelError, match="timed out"),
        pw.staged_payload(repo, target, b"x", lock_timeout=0),
    ):
        pass
    lock.unlink()
    with (
        pytest.raises(pw.PlatformWheelError, match="non-negative"),
        pw.staged_payload(repo, target, b"x", lock_timeout=-1),
    ):
        pass
    shutil_repo = tmp_path / "not-repo"
    shutil_repo.mkdir()
    with (
        pytest.raises(pw.PlatformWheelError, match="package directory"),
        pw.staged_payload(shutil_repo, target, b"x"),
    ):
        pass


def test_staged_payload_rejects_symlink_lock_or_staging(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    package_root = repo / "src" / "local_shell_mcp"
    target = pw.target_for_tag("linux_x86_64")
    external = tmp_path / "external"
    external.mkdir()
    lock = pw._platform_wheel_lock_path(repo)
    try:
        lock.symlink_to(external / "lock")
    except OSError:
        pytest.skip("symlinks unavailable")
    with (
        pytest.raises(pw.PlatformWheelError, match="symlink.*lock"),
        pw.staged_payload(repo, target, b"x", lock_timeout=0),
    ):
        pass
    lock.unlink()
    (package_root / "ui_runtime").symlink_to(external, target_is_directory=True)
    with (
        pytest.raises(pw.PlatformWheelError, match="symlink staging"),
        pw.staged_payload(repo, target, b"x"),
    ):
        pass
    assert not lock.exists()
    assert not (package_root / pw._LOCK_NAME).exists()


def test_staged_payload_rejects_nonregular_lock(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    lock = pw._platform_wheel_lock_path(repo)
    lock.mkdir()
    with (
        pytest.raises(pw.PlatformWheelError, match="not a regular file"),
        pw.staged_payload(repo, target, b"x", lock_timeout=0),
    ):
        pass
    assert lock.is_dir()
    lock.rmdir()


def test_staged_payload_rejects_lock_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    lock = pw._platform_wheel_lock_path(repo)
    monkeypatch.setattr(pw, "_same_file_identity", lambda *_args: False)
    with (
        pytest.raises(pw.PlatformWheelError, match="changed while.*acquired"),
        pw.staged_payload(repo, target, b"x"),
    ):
        pass
    assert lock.is_file()
    lock.unlink()


def test_staged_payload_does_not_remove_changed_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    lock = pw._platform_wheel_lock_path(repo)
    with (
        pytest.raises(pw.PlatformWheelError, match="safely remove"),
        pw.staged_payload(repo, target, b"x"),
    ):
        monkeypatch.setattr(pw, "_same_file_identity", lambda *_args: False)
    assert lock.is_file()
    lock.unlink()


def test_inspect_wheel_rejects_packaged_build_lock(tmp_path: Path) -> None:
    path = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        payloads={f"local_shell_mcp/{pw._LOCK_NAME}": b"pid=123\n"},
    )
    with pytest.raises(pw.PlatformWheelError, match="build lock"):
        pw.inspect_wheel(path, target=None)


def test_platform_wheel_lock_path_is_stable_and_external(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    first = pw._platform_wheel_lock_path(repo)
    assert first == pw._platform_wheel_lock_path(repo)
    assert first != pw._platform_wheel_lock_path(other)
    assert first.name.startswith("local-shell-mcp-wheel-")
    assert repo not in first.parents


def test_rewrite_and_inspect_platform_wheel(tmp_path: Path) -> None:
    target = pw.target_for_tag("linux_x86_64")
    executable = _executable(target, b"real")
    payload = pw.deterministic_gzip(executable)
    universal = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        payloads={target.payload_path: payload},
    )
    output, inspection = pw.rewrite_platform_wheel(
        universal,
        tmp_path / "out",
        target,
        payload,
        expected_payload_sha256=hashlib.sha256(payload).hexdigest(),
        expected_executable_sha256=hashlib.sha256(executable).hexdigest(),
    )
    assert output.name == "local_shell_mcp-1.0-py3-none-linux_x86_64.whl"
    assert inspection.root_is_purelib is False
    assert inspection.platform_tag == "linux_x86_64"
    assert inspection.executable_size == len(executable)
    with WheelFile(output, "r") as wheel:
        assert wheel.getinfo(target.payload_path).compress_type == ZIP_STORED
        assert wheel.read(target.payload_path) == payload
        wheel_metadata = wheel.read("local_shell_mcp-1.0.dist-info/WHEEL")
        assert b"Root-Is-Purelib: false" in wheel_metadata
        assert b"Tag: py3-none-linux_x86_64" in wheel_metadata
        assert {info.date_time for info in wheel.infolist()} == {
            pw._ZIP_TIMESTAMP
        }
        assert all(
            not info.extra and not info.comment for info in wheel.infolist()
        )
        for name in wheel.namelist():
            wheel.read(name)


def test_rewrite_platform_wheel_is_byte_reproducible(tmp_path: Path) -> None:
    target = pw.target_for_tag("linux_x86_64")
    executable = _executable(target, b"reproducible")
    payload = pw.deterministic_gzip(executable)
    universal = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        payloads={target.payload_path: payload},
    )
    outputs = []
    for directory in (tmp_path / "first", tmp_path / "second"):
        output, _inspection = pw.rewrite_platform_wheel(
            universal,
            directory,
            target,
            payload,
            expected_payload_sha256=hashlib.sha256(payload).hexdigest(),
            expected_executable_sha256=hashlib.sha256(executable).hexdigest(),
        )
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]


def test_inspect_universal_wheel_requires_no_payload(tmp_path: Path) -> None:
    universal = _make_wheel(tmp_path / "local_shell_mcp-1.0-py3-none-any.whl")
    inspection = pw.inspect_wheel(universal, target=None)
    assert inspection.platform_tag == "any"
    assert inspection.payload_path is None
    target = pw.target_for_tag("linux_x86_64")
    with_payload = _make_wheel(
        tmp_path / "other-1.0-py3-none-any.whl",
        payloads={
            target.payload_path: pw.deterministic_gzip(_executable(target))
        },
    )
    with pytest.raises(pw.PlatformWheelError, match="must not contain"):
        pw.inspect_wheel(with_payload, target=None)


def test_inspect_platform_wheel_rejects_extra_or_corrupt_payload(
    tmp_path: Path,
) -> None:
    target = pw.target_for_tag("linux_x86_64")
    platform_metadata = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
        b"Tag: py3-none-linux_x86_64\n"
    )
    extra = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-linux_x86_64.whl",
        wheel_metadata=platform_metadata,
        payloads={
            target.payload_path: b"bad",
            f"{pw.PAYLOAD_PACKAGE_PREFIX}extra": b"x",
        },
    )
    with pytest.raises(pw.PlatformWheelError, match="exactly"):
        pw.inspect_wheel(extra, target=target)
    corrupt = _make_wheel(
        tmp_path / "other-1.0-py3-none-linux_x86_64.whl",
        wheel_metadata=platform_metadata,
        payloads={target.payload_path: b"bad"},
    )
    with pytest.raises(pw.PlatformWheelError, match="valid gzip"):
        pw.inspect_wheel(corrupt, target=target)


def test_inspect_platform_wheel_requires_stored_payload(tmp_path: Path) -> None:
    target = pw.target_for_tag("linux_x86_64")
    platform_metadata = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
        b"Tag: py3-none-linux_x86_64\n"
    )
    executable = _executable(target)
    wheel = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-linux_x86_64.whl",
        wheel_metadata=platform_metadata,
        payloads={target.payload_path: pw.deterministic_gzip(executable)},
    )
    with pytest.raises(pw.PlatformWheelError, match="ZIP_STORED"):
        pw.inspect_wheel(wheel, target=target)


def test_inspect_wheel_rejects_filename_metadata_disagreement(
    tmp_path: Path,
) -> None:
    wrong = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-linux_x86_64.whl",
    )
    with pytest.raises(pw.PlatformWheelError, match="disagree"):
        pw.inspect_wheel(wrong, target=pw.target_for_tag("linux_x86_64"))


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (b"Wheel-Version: 1.0\nTag: py3-none-any\n", "Root-Is-Purelib"),
        (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: maybe\nTag: py3-none-any\n",
            "Root-Is-Purelib",
        ),
        (b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\n", "no Tag"),
        (b"\xff", "UTF-8"),
    ],
)
def test_inspect_wheel_rejects_bad_wheel_metadata(
    tmp_path: Path,
    metadata: bytes,
    message: str,
) -> None:
    path = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        wheel_metadata=metadata,
    )
    with pytest.raises(pw.PlatformWheelError, match=message):
        pw.inspect_wheel(path, target=None)


def test_wheel_members_rejects_invalid_archive_and_missing_metadata(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "local_shell_mcp-1.0-py3-none-any.whl"
    invalid.write_bytes(b"bad")
    with pytest.raises(pw.PlatformWheelError, match="invalid wheel archive"):
        pw._wheel_members(invalid)
    missing = tmp_path / "other-1.0-py3-none-any.whl"
    with WheelFile(missing, "w") as wheel:
        wheel.writestr("other/__init__.py", b"")
    with pytest.raises(pw.PlatformWheelError, match="exactly one"):
        pw._wheel_members(missing)


def test_wheel_members_requires_each_unread_payload(tmp_path: Path) -> None:
    target = pw.target_for_tag("linux_x86_64")
    universal = _make_wheel(tmp_path / "local_shell_mcp-1.0-py3-none-any.whl")
    with pytest.raises(pw.PlatformWheelError, match="unread native payload"):
        pw._wheel_members(
            universal,
            unread_names=frozenset({target.payload_path}),
        )


def test_rewrite_does_not_read_staged_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = pw.target_for_tag("linux_x86_64")
    executable = _executable(target, b"in-memory")
    payload = pw.deterministic_gzip(executable)
    universal = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        payloads={target.payload_path: b"not-valid-gzip"},
    )
    original_read = pw.WheelFile.read

    def guarded_read(wheel: WheelFile, name: str) -> bytes:
        if (
            Path(str(wheel.filename)) == universal
            and name == target.payload_path
        ):
            raise AssertionError("staged payload must not be read")
        return original_read(wheel, name)

    monkeypatch.setattr(pw.WheelFile, "read", guarded_read)
    output, inspection = pw.rewrite_platform_wheel(
        universal,
        tmp_path / "out",
        target,
        payload,
        expected_payload_sha256=hashlib.sha256(payload).hexdigest(),
        expected_executable_sha256=hashlib.sha256(executable).hexdigest(),
    )
    assert output.exists()
    assert inspection.payload_sha256 == hashlib.sha256(payload).hexdigest()


def test_rewrite_rejects_bad_input_and_digest_mismatch(tmp_path: Path) -> None:
    target = pw.target_for_tag("linux_x86_64")
    payload = pw.deterministic_gzip(_executable(target))
    universal = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        payloads={target.payload_path: payload},
    )
    out = tmp_path / "out"
    with pytest.raises(pw.PlatformWheelError, match="payload digest"):
        pw.rewrite_platform_wheel(
            universal,
            out,
            target,
            payload,
            expected_payload_sha256="0" * 64,
            expected_executable_sha256=hashlib.sha256(
                _executable(target)
            ).hexdigest(),
        )
    assert not list(out.glob("*.whl"))
    tagged = _make_wheel(
        tmp_path / "other-1.0-py3-none-linux_x86_64.whl",
        wheel_metadata=(
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
            b"Tag: py3-none-linux_x86_64\n"
        ),
        payloads={target.payload_path: payload},
    )
    with pytest.raises(pw.PlatformWheelError, match="input filename"):
        pw.rewrite_platform_wheel(
            tagged,
            out,
            target,
            payload,
            expected_payload_sha256="",
            expected_executable_sha256="",
        )


def test_rewrite_refuses_existing_output(tmp_path: Path) -> None:
    target = pw.target_for_tag("linux_x86_64")
    executable = _executable(target)
    payload = pw.deterministic_gzip(executable)
    universal = _make_wheel(
        tmp_path / "local_shell_mcp-1.0-py3-none-any.whl",
        payloads={target.payload_path: payload},
    )
    out = tmp_path / "out"
    out.mkdir()
    expected = out / "local_shell_mcp-1.0-py3-none-linux_x86_64.whl"
    expected.write_bytes(b"existing")
    with pytest.raises(pw.PlatformWheelError, match="already exists"):
        pw.rewrite_platform_wheel(
            universal,
            out,
            target,
            payload,
            expected_payload_sha256=hashlib.sha256(payload).hexdigest(),
            expected_executable_sha256=hashlib.sha256(executable).hexdigest(),
        )
    assert expected.read_bytes() == b"existing"


def test_decompress_payload_enforces_all_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(pw.PlatformWheelError, match="empty"):
        pw._decompress_payload(b"")
    monkeypatch.setattr(pw, "MAX_COMPRESSED_BYTES", 1)
    with pytest.raises(pw.PlatformWheelError, match="gzip exceeds"):
        pw._decompress_payload(b"12")
    monkeypatch.setattr(pw, "MAX_COMPRESSED_BYTES", 1000)
    monkeypatch.setattr(pw, "MAX_EXECUTABLE_BYTES", 2)
    with pytest.raises(pw.PlatformWheelError, match="executable exceeds"):
        pw._decompress_payload(gzip.compress(b"123"))


def test_decompress_payload_wraps_zlib_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenGzip:
        def __enter__(self) -> BrokenGzip:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            raise zlib.error("invalid distance too far back")

    monkeypatch.setattr(pw.gzip, "GzipFile", lambda **_kwargs: BrokenGzip())
    with pytest.raises(pw.PlatformWheelError, match="not valid gzip"):
        pw._decompress_payload(b"not-empty")


def test_inspect_sdist_accepts_source_and_rejects_generated_files(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good.tar.gz"
    with tarfile.open(good, "w:gz") as archive:
        info = tarfile.TarInfo("project/ui-opentui/src/index.ts")
        data = b"source"
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    pw.inspect_sdist(good)
    bad_payload = tmp_path / "payload.tar.gz"
    with tarfile.open(bad_payload, "w:gz") as archive:
        info = tarfile.TarInfo(
            "project/src/local_shell_mcp/ui_runtime/local-shell-mcp-tui.gz"
        )
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(pw.PlatformWheelError, match="embedded"):
        pw.inspect_sdist(bad_payload)
    bad_generated = tmp_path / "generated.tar.gz"
    with tarfile.open(bad_generated, "w:gz") as archive:
        info = tarfile.TarInfo("project/ui-opentui/dist/local-shell-mcp-tui")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(pw.PlatformWheelError, match="generated"):
        pw.inspect_sdist(bad_generated)
    invalid = tmp_path / "invalid.tar.gz"
    invalid.write_bytes(b"bad")
    with pytest.raises(pw.PlatformWheelError, match="invalid sdist"):
        pw.inspect_sdist(invalid)


def test_build_staged_universal_wheel_requires_exactly_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pw,
        "_run_checked",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )
    build = tmp_path / "build"
    build.mkdir()
    with pytest.raises(pw.PlatformWheelError, match="0 wheels"):
        pw._build_staged_universal_wheel(tmp_path, build, uv_executable="uv")
    (build / "a.whl").write_bytes(b"a")
    (build / "b.whl").write_bytes(b"b")
    with pytest.raises(pw.PlatformWheelError, match="2 wheels"):
        pw._build_staged_universal_wheel(tmp_path, build, uv_executable="uv")


def test_build_platform_wheel_orchestrates_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path)
    target = pw.target_for_tag("linux_x86_64")
    executable = _executable(target, b"orchestrated")
    monkeypatch.setattr(
        pw, "compile_opentui", lambda *_args, **_kwargs: executable
    )

    def fake_build(
        repo_root: Path,
        build_dir: Path,
        *,
        uv_executable: str,
    ) -> Path:
        assert repo_root == repo.resolve()
        assert uv_executable == "custom-uv"
        payload_path = (
            repo
            / "src"
            / "local_shell_mcp"
            / "ui_runtime"
            / (f"{target.executable_name}.gz")
        )
        assert payload_path.is_file()
        return _make_wheel(
            build_dir / "local_shell_mcp-1.0-py3-none-any.whl",
            payloads={target.payload_path: payload_path.read_bytes()},
        )

    monkeypatch.setattr(pw, "_build_staged_universal_wheel", fake_build)
    output, inspection = pw.build_platform_wheel(
        repo,
        tmp_path / "out",
        target,
        bun_executable="custom-bun",
        uv_executable="custom-uv",
    )
    assert output.is_file()
    assert (
        inspection.executable_sha256 == hashlib.sha256(executable).hexdigest()
    )
    assert not (repo / "src" / "local_shell_mcp" / "ui_runtime").exists()


def test_main_reports_success_and_stable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = pw.target_for_tag("linux_x86_64")
    output = tmp_path / "wheel.whl"
    inspection = pw.WheelInspection(
        path=str(output),
        platform_tag=target.tag,
        root_is_purelib=False,
        payload_path=target.payload_path,
        payload_sha256="a",
        executable_sha256="b",
        compressed_size=1,
        executable_size=2,
    )
    monkeypatch.setattr(
        pw,
        "build_platform_wheel",
        lambda *_args, **_kwargs: (output, inspection),
    )
    assert (
        pw.main(["--platform-tag", target.tag, "--output-dir", str(tmp_path)])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["platform_tag"] == target.tag

    def fail(
        *_args: object, **_kwargs: object
    ) -> tuple[Path, pw.WheelInspection]:
        raise pw.PlatformWheelError("safe failure")

    monkeypatch.setattr(pw, "build_platform_wheel", fail)
    assert pw.main(["--platform-tag", target.tag]) == 1
    assert "safe failure" in capsys.readouterr().err
