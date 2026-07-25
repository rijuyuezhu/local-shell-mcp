from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_ROOT = _REPO_ROOT / "scripts"
_DOCKER_ENTRYPOINT = _SCRIPTS_ROOT / "docker-entrypoint.sh"
_CLOUDFLARE_HELPER = _SCRIPTS_ROOT / "run-with-cloudflare-tunnel.sh"


def test_scripts_root_has_one_explicit_owner_set() -> None:
    root_files = {
        path.name
        for path in _SCRIPTS_ROOT.iterdir()
        if path.is_file() or path.is_symlink()
    }
    root_directories = {
        path.name
        for path in _SCRIPTS_ROOT.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }

    assert root_files == {
        "README.md",
        "docker-entrypoint.sh",
        "run-with-cloudflare-tunnel.sh",
    }
    assert root_directories == {
        "generation",
        "release",
        "testing",
        "validation",
    }
    assert all(
        path.is_file() and not path.is_symlink()
        for path in (_DOCKER_ENTRYPOINT, _CLOUDFLARE_HELPER)
    )


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX bash is unavailable",
)
def test_root_deployment_shell_interfaces_parse() -> None:
    for path in (_DOCKER_ENTRYPOINT, _CLOUDFLARE_HELPER):
        completed = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        content = path.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")


def test_docker_entrypoint_path_is_an_image_build_and_startup_abi() -> None:
    dockerfile = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh"
    ) in dockerfile
    assert "chmod +x /usr/local/bin/docker-entrypoint.sh" in dockerfile
    assert 'ENTRYPOINT ["docker-entrypoint.sh"]' in dockerfile


def test_cloudflare_helper_path_is_a_documented_executable_interface() -> None:
    index_entry = subprocess.run(
        [
            "git",
            "ls-files",
            "-s",
            "--",
            _CLOUDFLARE_HELPER.relative_to(_REPO_ROOT).as_posix(),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert index_entry.split(maxsplit=1)[0] == "100755"

    quickstart = (_REPO_ROOT / "docs/getting-started/quickstart.md").read_text(
        encoding="utf-8"
    )
    tunnel = (
        _REPO_ROOT / "docs/getting-started/cloudflare-tunnel.md"
    ).read_text(encoding="utf-8")
    invocation = "scripts/run-with-cloudflare-tunnel.sh"

    assert quickstart.count(invocation) == 2
    assert f"ExecStart=/usr/bin/env bash {invocation}" in quickstart
    assert tunnel.count(invocation) == 1


def test_scripts_readme_documents_the_root_compatibility_contract() -> None:
    ownership = (_SCRIPTS_ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Root deployment interfaces" in ownership
    assert (
        "Only three tracked files may live directly under `scripts/`"
        in ownership
    )
    assert "`docker-entrypoint.sh`" in ownership
    assert "`run-with-cloudflare-tunnel.sh`" in ownership
    assert "container build/startup ABI" in ownership
    assert "stable user-facing deployment interface" in ownership
