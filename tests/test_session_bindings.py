from dataclasses import replace

import pytest

from local_shell_mcp.tool_session.bindings import (
    LocalSessionBinding,
    RemoteSessionBinding,
    binding_from_record,
)
from local_shell_mcp.tool_session.records import (
    AgentSession,
    session_to_payload,
)


def _local_record() -> AgentSession:
    return AgentSession(
        session_id="LOCAL001",
        target="local",
        workdir="/workspace/local",
        machine=None,
        worker_session_id=None,
        created_at=1.0,
        updated_at=2.0,
    )


def _remote_record() -> AgentSession:
    return AgentSession(
        session_id="REMOTE01",
        target="remote",
        workdir="/workspace/remote",
        machine="worker-a",
        worker_session_id="WORKER01",
        created_at=1.0,
        updated_at=2.0,
    )


def test_binding_from_record_returns_discriminated_local_binding() -> None:
    binding = binding_from_record(_local_record())

    assert binding == LocalSessionBinding(
        session_id="LOCAL001", workdir="/workspace/local"
    )
    assert binding.target == "local"


def test_binding_from_record_returns_complete_remote_binding() -> None:
    binding = binding_from_record(_remote_record())

    assert binding == RemoteSessionBinding(
        session_id="REMOTE01",
        workdir="/workspace/remote",
        machine="worker-a",
        worker_session_id="WORKER01",
    )
    assert binding.target == "remote"


@pytest.mark.parametrize(
    "record, message",
    [
        (replace(_remote_record(), machine=None), "missing its worker binding"),
        (
            replace(_remote_record(), worker_session_id=None),
            "missing its worker binding",
        ),
        (replace(_local_record(), machine="worker-a"), "remote worker binding"),
        (replace(_local_record(), workdir=""), "empty workdir"),
    ],
)
def test_binding_from_record_rejects_impossible_record_shapes(
    record: AgentSession, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        binding_from_record(record)


def test_session_to_payload_rejects_noncanonical_record() -> None:
    with pytest.raises(ValueError, match="not canonical"):
        session_to_payload(replace(_local_record(), machine="worker-a"))
