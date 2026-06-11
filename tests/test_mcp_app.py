from starlette.applications import Starlette
from starlette.routing import Route

import local_shell_mcp.mcp_app as mcp_app
from local_shell_mcp.config.settings import Settings, configure_settings


async def _ok(request):  # noqa: ANN001
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


def test_build_mcp_http_app_wraps_mcp_with_oauth_routes():
    configure_settings(
        Settings(mode="mcp", auth_mode="none", remote_enabled=False)
    )

    app = mcp_app.build_mcp_http_app(_DummyMcp())

    assert app is not None
    paths = _route_paths(app)
    assert paths[:3] == [
        "/healthz",
        "/readyz",
        "/.well-known/oauth-protected-resource",
    ]
    assert "/oauth/token" in paths
    assert paths[-1] == ""


def test_build_mcp_http_app_includes_remote_routes_when_enabled():
    configure_settings(
        Settings(mode="mcp", auth_mode="none", remote_enabled=True)
    )

    app = mcp_app.build_mcp_http_app(_DummyMcp())

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
