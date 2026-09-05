import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workgate.config.settings import clear_settings_cache, get_settings
from workgate.ops.downloads import (
    create_file_link_dispatch_execute,
    list_file_links_execute,
)
from workgate.ops.utils.download_snapshot import snapshot_directory
from workgate.ops.utils.download_store import backup_path, store_path


def _configure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKGATE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKGATE_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("WORKGATE_BASE_URL", "https://files.example.test")
    monkeypatch.setenv("WORKGATE_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()


def _create_file_link(path: str) -> None:
    asyncio.run(create_file_link_dispatch_execute(path, ttl_s=60))


def test_concurrent_processes_do_not_lose_links(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    sources = []
    for index in range(6):
        source = tmp_path / f"artifact-{index}.txt"
        source.write_text(f"payload-{index}", encoding="utf-8")
        sources.append(source.name)

    script = """
import sys
from workgate.config.settings import clear_settings_cache
from workgate.ops.downloads import create_file_link_dispatch_execute
clear_settings_cache()
__import__("asyncio").run(create_file_link_dispatch_execute(sys.argv[1], ttl_s=60))
"""
    environment = os.environ.copy()
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, source],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for source in sources
    ]
    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            failures.append((process.returncode, stdout, stderr))

    assert failures == []
    clear_settings_cache()
    links = list_file_links_execute().links
    assert len(links) == len(sources)
    assert {Path(link.path or "").name for link in links} == set(sources)
    assert len(list(snapshot_directory().glob("*.bin"))) == len(sources)


def test_corrupt_primary_and_backup_refuse_silent_reset(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    (tmp_path / "artifact.txt").write_text("payload", encoding="utf-8")
    _create_file_link("artifact.txt")
    store_path().write_text("{broken-primary", encoding="utf-8")
    backup_path().write_text("{broken-backup", encoding="utf-8")

    with pytest.raises(RuntimeError, match="no valid backup"):
        list_file_links_execute()

    assert store_path().read_text(encoding="utf-8") == "{broken-primary"
    assert backup_path().read_text(encoding="utf-8") == "{broken-backup"
    assert len(list(snapshot_directory().glob("*.bin"))) == 1


def test_legacy_live_path_links_are_dropped_on_migration(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    state_dir = get_settings().state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    legacy = {
        "version": 1,
        "links": {
            "legacy-token": {
                "path": str(tmp_path / "live-secret.txt"),
                "display_path": "live-secret.txt",
                "filename": "live-secret.txt",
                "expires_at": 9_999_999_999,
                "downloads": 0,
                "max_downloads": 0,
            }
        },
    }
    store_path().write_text(json.dumps(legacy), encoding="utf-8")

    assert list_file_links_execute().links == []
    assert json.loads(store_path().read_text(encoding="utf-8")) == {
        "links": {},
        "version": 2,
    }
    assert json.loads(backup_path().read_text(encoding="utf-8")) == {
        "links": {},
        "version": 2,
    }


def test_prune_removes_only_stale_staging_files(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    directory = snapshot_directory()
    stale = directory / ".stale.tmp"
    recent = directory / ".recent.tmp"
    stale.write_bytes(b"stale")
    recent.write_bytes(b"recent")
    old = 1_700_000_000
    os.utime(stale, (old, old))

    list_file_links_execute()

    assert not stale.exists()
    assert recent.read_bytes() == b"recent"
