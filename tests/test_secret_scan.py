import pytest

from workgate.config.settings import clear_settings_cache
from workgate.ops.files import write_file_execute
from workgate.ops.secret_scan import (
    _is_placeholder_secret_match,
    secret_scan_execute,
)


@pytest.mark.asyncio
async def testsecret_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKGATE_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    fake_token = "gh" + "p_" + "1234567890123456789012345678901234567890"
    write_file_execute("x.py", f"TOKEN = '{fake_token}'")
    result = await secret_scan_execute(".")
    assert result.findings


@pytest.mark.asyncio
async def test_secret_scan_respects_gitignore(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKGATE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKGATE_RG_BIN", "missing-rg-for-test")
    clear_settings_cache()
    write_file_execute(".gitignore", "ignored.txt\n")
    ignored_token = "gh" + "p_" + "1234567890123456789012345678901234567890"
    visible_token = "gh" + "p_" + "abcdefghijklmnopqrstuvwxy1234567890123"
    write_file_execute("ignored.txt", f"TOKEN = '{ignored_token}'")
    write_file_execute("visible.txt", f"TOKEN = '{visible_token}'")

    result = await secret_scan_execute(".")

    paths = {finding.path for finding in result.findings}
    assert "visible.txt" in paths
    assert "ignored.txt" not in paths


def test_secret_scan_ignores_obvious_placeholder_assignments():
    assert _is_placeholder_secret_match(
        "generic_assignment", "SECRET = '${EXAMPLE:-dev-change-me}'"
    )
    assert _is_placeholder_secret_match(
        "generic_assignment",
        "OAUTH_SECRET = 'ci-workgate-secret-fixture'",
    )
    assert not _is_placeholder_secret_match(
        "generic_assignment", "SECRET = 'realistic-live-value-123'"
    )
    assert not _is_placeholder_secret_match(
        "github_token", "TOKEN = 'ghp_1234567890123456789012345678901234567890'"
    )
