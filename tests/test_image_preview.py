from __future__ import annotations

from typing import Any

import pytest

import local_shell_mcp.image_preview as preview_module


class _OversizedImage:
    size = (5_001, 5_000)

    def __enter__(self) -> _OversizedImage:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def seek(self, frame: int) -> None:
        assert frame == 0


def test_source_pixel_limit_is_checked_before_orientation_or_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preview_module.Image,
        "open",
        lambda _source: _OversizedImage(),
    )

    def fail_transpose(_image: Any) -> Any:
        raise AssertionError("oversized image must be rejected before decoding")

    monkeypatch.setattr(
        preview_module.ImageOps, "exif_transpose", fail_transpose
    )

    with pytest.raises(ValueError, match="25005000 pixels"):
        preview_module.make_image_preview(b"header", 80, 24)
