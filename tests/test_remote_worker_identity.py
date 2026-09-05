import json

import pytest

import workgate.remote_worker.identity as worker_identity
from workgate.remote_worker.state import worker_identity_path


def test_identity_validation_and_deletion_fail_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    path = worker_identity_path()

    path.write_text("[]", encoding="utf-8")
    assert worker_identity.read_worker_identity() is None

    path.write_text(
        json.dumps({"server": "https://controller.test", "access": "x"}),
        encoding="utf-8",
    )
    assert worker_identity.read_worker_identity() is None

    path.unlink()
    with pytest.raises(ValueError, match="no stored worker identity"):
        worker_identity.load_worker_identity()

    worker_identity.write_worker_identity(
        {
            "server": "https://controller.test",
            "name": "edge-a",
            "access": "x",
            "workdir": "",
        }
    )
    with pytest.raises(ValueError, match="missing workdir"):
        worker_identity.load_worker_identity()

    worker_identity.delete_worker_identity()
    assert not path.exists()
    worker_identity.delete_worker_identity()
