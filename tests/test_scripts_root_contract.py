import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLOUDFLARE_HELPER = _REPO_ROOT / "scripts" / "run-with-cloudflare-tunnel.sh"


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX bash is unavailable",
)
def test_cloudflare_helper_is_valid_executable_script() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(_CLOUDFLARE_HELPER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

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
