import enum
from dataclasses import dataclass
from pathlib import Path

from local_shell_mcp.remote_worker.serialization import to_jsonable


class _Mode(enum.Enum):
    READY = "ready"


@dataclass(frozen=True)
class _Record:
    path: Path
    value: bytes


class _Model:
    def model_dump(self, *, mode: str, exclude_none: bool):
        assert mode == "json"
        return {"value": 1, **({} if exclude_none else {"empty": None})}


def test_worker_serialization_handles_dependency_light_value_shapes():
    payload = {
        "bytes": b"hello\xff",
        "path": Path("workspace/file.txt"),
        "enum": _Mode.READY,
        "model": _Model(),
        "record": _Record(Path("record.txt"), b"value"),
        "sequence": (1, None),
        "set": {"one", "two"},
        "none": None,
    }

    result = to_jsonable(payload, exclude_none=True)

    assert result["bytes"].startswith("hello")
    assert result["path"] == str(Path("workspace/file.txt"))
    assert result["enum"] == "ready"
    assert result["model"] == {"value": 1}
    assert result["record"] == {
        "path": str(Path("record.txt")),
        "value": "value",
    }
    assert result["sequence"] == [1, None]
    assert sorted(result["set"]) == ["one", "two"]
    assert "none" not in result
