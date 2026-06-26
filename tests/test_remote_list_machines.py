from local_shell_mcp.remote import RemoteManager, RemoteWorker
from local_shell_mcp.settings import get_settings


def test_list_machines_reports_counts_and_details(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    manager = RemoteManager()
    now = 1_000_000.0
    monkeypatch.setattr("local_shell_mcp.remote._utc", lambda: now)

    recent = RemoteWorker(name="recent-worker", token="recent", last_seen=now - 5)
    stale = RemoteWorker(name="stale-worker", token="stale", last_seen=now - 500)
    manager.workers = {recent.name: recent, stale.name: stale}
    manager.tokens = {recent.token: recent.name, stale.token: stale.name}
    recent.queue.put_nowait({"id": "job-1"})

    result = manager.list_machines()

    assert result["counts"] == {"online": 1, "offline": 1, "total": 2}
    assert [machine["name"] for machine in result["machines"]] == ["recent-worker", "stale-worker"]
    assert result["machines"][0]["status"] == "online"
    assert result["machines"][0]["last_seen_age_s"] == 5
    assert result["machines"][0]["queue_depth"] == 1
    assert result["machines"][1]["status"] == "offline"
