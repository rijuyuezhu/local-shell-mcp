import base64
import os

import pytest
from fastapi.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.oauth.core.scopes import (
    SCOPE_SHELL_READ,
    SCOPE_SHELL_WRITE,
)
from local_shell_mcp.oauth.protocol.token_codec import issue_access_token
from local_shell_mcp.server.http.app import build_http_app

BASE_URL = "https://local-shell-mcp.example"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZP2sAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def _reset_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def _configure(
    monkeypatch,
    workspace,
    *,
    auth_mode="none",
    allow_full_control=False,
    **values,
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(workspace / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", BASE_URL)
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL",
        str(allow_full_control).lower(),
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    for name, value in values.items():
        monkeypatch.setenv(
            f"LOCAL_SHELL_MCP_{name.upper()}", str(value).lower()
        )
    clear_settings_cache()


def _client(monkeypatch, workspace, **values) -> TestClient:
    _configure(monkeypatch, workspace, **values)
    return TestClient(
        build_http_app(),
        base_url=BASE_URL,
        client=("203.0.113.11", 50001),
    )


def _token(scope: str) -> str:
    return issue_access_token(
        client_id="webui-files-test",
        scope=scope,
        resource=f"{BASE_URL}/mcp",
    )


def test_file_listing_is_sorted_bounded_and_workspace_relative(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "z-dir").mkdir()
    (workspace / "a-dir").mkdir()
    (workspace / "z.txt").write_text("z", encoding="utf-8")
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / ".hidden").write_text("hidden", encoding="utf-8")
    client = _client(monkeypatch, workspace)

    response = client.get("/api/ui/files", params={"path": "."})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["path"] == "."
    assert payload["parent"] == "."
    assert payload["is_truncated"] is False
    assert [entry["name"] for entry in payload["entries"]] == [
        ".state",
        "a-dir",
        "z-dir",
        ".hidden",
        "a.txt",
        "z.txt",
    ]
    hidden = next(
        entry for entry in payload["entries"] if entry["name"] == ".hidden"
    )
    assert hidden["hidden"] is True
    assert all(not os.path.isabs(entry["path"]) for entry in payload["entries"])


def test_file_api_stays_inside_workspace_even_in_full_control_mode(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (workspace / "outside-link").symlink_to(outside, target_is_directory=True)
    client = _client(
        monkeypatch,
        workspace,
        allow_full_control=True,
    )

    listed = client.get("/api/ui/files", params={"path": str(outside)})
    previewed = client.get(
        "/api/ui/files/preview",
        params={"path": str(outside / "secret.txt")},
    )
    written = client.post(
        "/api/ui/files/write",
        json={"path": str(outside / "new.txt"), "content": "escape"},
    )
    linked_write = client.post(
        "/api/ui/files/write",
        json={"path": "outside-link/linked.txt", "content": "escape"},
    )

    for response in (listed, previewed, written, linked_write):
        assert response.status_code == 400
        assert "escapes workspace" in response.json()["message"].lower()
    assert not (outside / "new.txt").exists()
    assert not (outside / "linked.txt").exists()


def test_file_preview_supports_text_binary_directory_and_raster_images(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    folder = workspace / "folder"
    folder.mkdir()
    (folder / "child.txt").write_text("child", encoding="utf-8")
    (workspace / "notes.txt").write_text("alpha\nbeta", encoding="utf-8")
    (workspace / "blob.bin").write_bytes(b"\x00\x01\xff")
    (workspace / "pixel.png").write_bytes(PNG_1X1)
    (workspace / "vector.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    client = _client(monkeypatch, workspace)

    directory = client.get(
        "/api/ui/files/preview", params={"path": "folder"}
    ).json()["data"]
    text = client.get(
        "/api/ui/files/preview", params={"path": "notes.txt"}
    ).json()["data"]
    binary = client.get(
        "/api/ui/files/preview", params={"path": "blob.bin"}
    ).json()["data"]
    image = client.get(
        "/api/ui/files/preview", params={"path": "pixel.png"}
    ).json()["data"]
    svg = client.get(
        "/api/ui/files/preview", params={"path": "vector.svg"}
    ).json()["data"]

    assert directory["kind"] == "directory"
    assert directory["entries"][0]["name"] == "child.txt"
    assert text["kind"] == "text"
    assert text["content"] == "alpha\nbeta"
    assert binary == {
        "kind": "binary",
        "path": "blob.bin",
        "bytes": 3,
        "media_type": "application/octet-stream",
        "preview_encoding": "hex",
        "preview_bytes": 3,
        "preview": "0001ff",
    }
    assert image["kind"] == "image"
    assert image["media_type"] == "image/png"
    assert image["inline"] is True
    assert base64.b64decode(image["data_base64"]) == PNG_1X1
    assert svg["kind"] == "text"
    assert svg["media_type"] == "image/svg+xml"
    assert "<script>" in svg["content"]
    assert "data_base64" not in svg


def test_editor_reads_complete_text_and_rejects_binary_or_truncated_files(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    complete = "\n".join(f"line-{index}" for index in range(40))
    (workspace / "complete.txt").write_text(complete, encoding="utf-8")
    (workspace / "binary.bin").write_bytes(b"\x00binary")
    (workspace / "large.txt").write_text("x" * 200, encoding="utf-8")
    client = _client(
        monkeypatch,
        workspace,
        max_file_read_bytes=64,
    )

    complete_response = client.get(
        "/api/ui/files/content", params={"path": "complete.txt"}
    )
    binary_response = client.get(
        "/api/ui/files/content", params={"path": "binary.bin"}
    )
    large_response = client.get(
        "/api/ui/files/content", params={"path": "large.txt"}
    )

    assert complete_response.status_code == 400
    assert "editor read limit" in complete_response.json()["message"]
    assert binary_response.status_code == 400
    assert "Binary files" in binary_response.json()["message"]
    assert large_response.status_code == 400
    assert "editor read limit" in large_response.json()["message"]

    clear_settings_cache()
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "4096")
    complete_client = TestClient(build_http_app(), base_url=BASE_URL)
    payload = complete_client.get(
        "/api/ui/files/content", params={"path": "complete.txt"}
    ).json()["data"]
    assert payload["content"] == complete
    assert payload["truncated"] is False


def test_file_mutations_require_write_scope_and_preserve_safe_semantics(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "mode.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)
    client = _client(monkeypatch, workspace, auth_mode="oauth")
    read_headers = {"Authorization": f"Bearer {_token(SCOPE_SHELL_READ)}"}
    write_headers = {
        "Authorization": (
            "Bearer " + _token(f"{SCOPE_SHELL_READ} {SCOPE_SHELL_WRITE}")
        )
    }

    assert client.get("/api/ui/files", headers=read_headers).status_code == 200
    denied = client.post(
        "/api/ui/files/write",
        json={"path": "mode.txt", "content": "new"},
        headers=read_headers,
    )
    assert denied.status_code == 403
    assert SCOPE_SHELL_WRITE in denied.text

    written = client.post(
        "/api/ui/files/write",
        json={"path": "mode.txt", "content": "new", "overwrite": True},
        headers=write_headers,
    )
    assert written.status_code == 200
    assert target.read_text(encoding="utf-8") == "new"
    assert target.stat().st_mode & 0o777 == 0o640

    created = client.post(
        "/api/ui/files/write",
        json={"path": "new.txt", "content": "created", "overwrite": False},
        headers=write_headers,
    )
    assert created.status_code == 200
    assert created.json()["data"]["created"] is True


def test_delete_refuses_workspace_root_and_unlinks_symlink_not_target(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    link = workspace / "outside-link"
    link.symlink_to(outside)
    client = _client(monkeypatch, workspace)

    root = client.post(
        "/api/ui/files/delete", json={"path": ".", "recursive": True}
    )
    deleted = client.post(
        "/api/ui/files/delete",
        json={"path": "outside-link", "recursive": False},
    )

    assert root.status_code == 400
    assert "workspace root" in root.json()["message"]
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] == "link"
    assert not link.exists()
    assert outside.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("", "path is required"),
        ("bad\x00path", "NUL"),
        ("x" * 4_097, "path exceeds"),
    ],
)
def test_file_api_rejects_invalid_paths(monkeypatch, tmp_path, path, message):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = _client(monkeypatch, workspace)

    response = client.get("/api/ui/files/preview", params={"path": path})

    assert response.status_code == 400
    assert message in response.json()["message"]
