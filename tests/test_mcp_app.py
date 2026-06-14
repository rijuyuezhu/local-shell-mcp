from typing import Any, cast

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import local_shell_mcp.mcp.app as mcp_app
from local_shell_mcp.config.settings import Settings, configure_settings


async def _ok(request):
    return None


class _DummyMcp:
    def __init__(self):
        self.transports = []

    def streamable_http_app(self):
        return Starlette(routes=[Route("/mcp", _ok)])

    def run(self, *, transport: str):
        self.transports.append(transport)


def _route_paths(app: Starlette) -> list[str]:
    return [getattr(route, "path", "") for route in app.routes]


def test_build_mcp_http_app_wraps_mcp_with_oauth_route_app():
    configure_settings(
        Settings(mode="mcp", auth_mode="none", remote_enabled=False)
    )

    app = mcp_app.build_mcp_http_app(cast(Any, _DummyMcp()))

    assert app is not None
    paths = _route_paths(app)
    assert paths[:2] == ["/healthz", "/readyz"]
    assert "/download/{token}" in paths
    assert "/.well-known/oauth-protected-resource" in paths
    assert paths.index("/download/{token}") < paths.index(
        "/.well-known/oauth-protected-resource"
    )
    assert "/oauth/token" in paths
    assert paths[-1] == ""


def test_build_mcp_http_app_includes_remote_routes_when_enabled():
    configure_settings(
        Settings(mode="mcp", auth_mode="none", remote_enabled=True)
    )

    app = mcp_app.build_mcp_http_app(cast(Any, _DummyMcp()))

    assert app is not None
    paths = _route_paths(app)
    assert "/join" in paths
    assert "/remote/register" in paths
    assert "/remote/poll" in paths


def test_run_mcp_uses_stdio_transport(monkeypatch):
    configure_settings(Settings(mode="stdio", auth_mode="none"))
    dummy = _DummyMcp()
    monkeypatch.setattr(mcp_app, "build_mcp", lambda: dummy)

    mcp_app.run_mcp()

    assert dummy.transports == ["stdio"]


def test_oauth_challenge_metadata_url_matches_rfc9728_path_resource():
    configure_settings(
        Settings(
            mode="mcp",
            auth_mode="oauth",
            remote_enabled=False,
            public_base_url="https://local-shell-mcp.example.com",
        )
    )

    app = mcp_app.build_mcp_http_app(cast(Any, _DummyMcp()))
    client = TestClient(app)

    response = client.get("/mcp")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://local-shell-mcp.example.com'
        '/.well-known/oauth-protected-resource/mcp"'
    )

    metadata = client.get("/.well-known/oauth-protected-resource/mcp")

    assert metadata.status_code == 200
    assert (
        metadata.json()["resource"] == "https://local-shell-mcp.example.com/mcp"
    )

    wrong_metadata = client.get("/.well-known/oauth-protected-resource/other")

    assert wrong_metadata.status_code == 404
