from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_checker():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "check-native-provenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "native_provenance_check", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_provenance_is_current() -> None:
    checker = _load_checker()
    assert checker.main() == 0


def test_native_provenance_hash_normalizes_line_endings(tmp_path: Path) -> None:
    checker = _load_checker()
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    lf.write_bytes(b"alpha\nbeta\n")
    crlf.write_bytes(b"alpha\r\nbeta\r\n")
    assert checker._sha256(lf) == checker._sha256(crlf)
