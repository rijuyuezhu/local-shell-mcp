from fastapi.testclient import TestClient

from local_shell_mcp import __version__
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.main import main
from local_shell_mcp.settings import get_settings
from local_shell_mcp.version import format_version_info, version_info


def test_version_info_reports_package_metadata():
    info = version_info()

    assert info["version"] == __version__
    assert info["package_version"]
    assert info["python"]
    assert info["platform"]
    assert format_version_info(info).startswith("local-shell-mcp ")


def test_cli_version_subcommand_prints_version(capsys):
    main(["version"])

    assert f"local-shell-mcp {__version__}" in capsys.readouterr().out


def test_cli_short_version_prints_raw_version(capsys):
    main(["--version"])

    assert capsys.readouterr().out.strip() == __version__


def test_http_version_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()

    response = TestClient(build_http_app()).get("/version")

    assert response.status_code == 200
    assert response.json()["version"] == __version__
