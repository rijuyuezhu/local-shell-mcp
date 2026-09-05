import json
from types import SimpleNamespace

import pytest

from workgate.ui.http import common as ui_common


def test_json_error_preserves_common_envelope() -> None:
    response = ui_common.json_error(ValueError("bad input"), status_code=409)

    assert response.status_code == 409
    assert json.loads(bytes(response.body)) == {
        "ok": False,
        "error": "ValueError",
        "message": "bad input",
    }


def test_bounded_text_normalizes_default_and_whitespace() -> None:
    assert (
        ui_common.bounded_text(
            None,
            field="machine",
            max_bytes=16,
            default=" local ",
            allow_empty=False,
        )
        == "local"
    )


def test_bounded_text_rejects_required_and_multibyte_overflow() -> None:
    with pytest.raises(ValueError, match="name is required"):
        ui_common.bounded_text(
            "   ", field="name", max_bytes=16, allow_empty=False
        )
    with pytest.raises(ValueError, match="name exceeds 3 encoded bytes"):
        ui_common.bounded_text("你好", field="name", max_bytes=3)


@pytest.mark.parametrize("value", [None, ""])
def test_bounded_int_uses_default(value: object) -> None:
    assert (
        ui_common.bounded_int(
            value,
            field="limit",
            default=25,
            minimum=1,
            maximum=100,
        )
        == 25
    )


@pytest.mark.parametrize("value", [True, "nope"])
def test_bounded_int_rejects_non_integer_values(value: object) -> None:
    with pytest.raises(ValueError, match="limit must be an integer"):
        ui_common.bounded_int(
            value,
            field="limit",
            default=25,
            minimum=1,
            maximum=100,
        )


def test_bounded_int_rejects_out_of_range_value() -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        ui_common.bounded_int(
            101,
            field="limit",
            default=25,
            minimum=1,
            maximum=100,
        )


def test_sorted_entry_payloads_places_directories_first() -> None:
    entries = [
        {"name": "beta", "type": "file"},
        {"name": "Zoo", "type": "dir"},
        {"name": "alpha", "type": "dir"},
        {"name": "Alpha", "type": "file"},
    ]

    rows = ui_common.sorted_entry_payloads(entries, dict)

    assert [(row["type"], row["name"]) for row in rows] == [
        ("dir", "alpha"),
        ("dir", "Zoo"),
        ("file", "Alpha"),
        ("file", "beta"),
    ]


def _patch_remote_inventory(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    machines: list[SimpleNamespace],
) -> None:
    monkeypatch.setattr(
        ui_common,
        "get_settings",
        lambda: SimpleNamespace(remote_enabled=enabled),
    )
    monkeypatch.setattr(
        ui_common,
        "remote_manager",
        lambda: SimpleNamespace(
            list_machines=lambda: SimpleNamespace(machines=machines)
        ),
    )


def test_require_remote_machine_rejects_disabled_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_inventory(monkeypatch, enabled=False, machines=[])

    with pytest.raises(ValueError, match="Remote workers are disabled"):
        ui_common.require_remote_machine("worker-a")


def test_require_remote_machine_rejects_unknown_and_offline_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_inventory(monkeypatch, enabled=True, machines=[])
    with pytest.raises(ValueError, match="Unknown remote machine: worker-a"):
        ui_common.require_remote_machine("worker-a")

    _patch_remote_inventory(
        monkeypatch,
        enabled=True,
        machines=[SimpleNamespace(name="worker-a", status="offline")],
    )
    with pytest.raises(
        ConnectionError, match="Remote machine worker-a is offline"
    ):
        ui_common.require_remote_machine("worker-a")


def test_require_remote_machine_accepts_online_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_remote_inventory(
        monkeypatch,
        enabled=True,
        machines=[SimpleNamespace(name="worker-a", status="online")],
    )

    ui_common.require_remote_machine("worker-a")
