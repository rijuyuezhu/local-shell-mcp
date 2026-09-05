from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Annotated, Any, Literal

import pytest

import local_shell_mcp.config.settings as settings_module
import local_shell_mcp.config.surface as surface
from local_shell_mcp.config.settings import Settings, load_settings
from local_shell_mcp.config.surface import (
    SETTING_SPECS,
    SPECS_BY_NAME,
    SettingSpec,
)


@dataclass(frozen=True)
class FakeField:
    annotation: Any


def test_path_defaults_use_portable_posix_separators():
    value = PureWindowsPath(r"\workspace\.local-shell-mcp")

    assert surface.default_to_string(value) == "/workspace/.local-shell-mcp"
    assert surface.yaml_default(value) == "/workspace/.local-shell-mcp"


def test_generated_yaml_example_loads_without_losing_defaults(monkeypatch):
    for spec in SETTING_SPECS:
        monkeypatch.delenv(spec.env_var, raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_CONFIG", raising=False)

    settings = load_settings("config.example.yaml")
    defaults = Settings()

    assert settings.command_denylist == defaults.command_denylist
    assert settings.path_denylist == defaults.path_denylist
    assert settings.allow_full_control == defaults.allow_full_control


def test_setting_spec_properties_cover_current_setting_shapes():
    assert SPECS_BY_NAME["port"].argparse_type is int
    assert SPECS_BY_NAME["tool_timeout_s"].argparse_type is float
    assert SPECS_BY_NAME["host"].argparse_type is str
    assert SPECS_BY_NAME["base_url"].argparse_type is str

    assert SPECS_BY_NAME["mode"].choices == ("mcp", "http", "both", "stdio")
    assert SPECS_BY_NAME["host"].choices is None

    assert not SPECS_BY_NAME["base_url"].is_bool
    assert SPECS_BY_NAME["base_url"].is_nullable
    assert not SPECS_BY_NAME["command_denylist"].is_nullable


def test_setting_spec_rejects_unregistered_setting() -> None:
    with pytest.raises(ValueError, match="Setting name not found"):
        SettingSpec("unregistered_setting", "Server")


def test_setting_spec_properties_cover_future_nullable_shapes(monkeypatch):
    monkeypatch.setattr(
        surface.Settings,
        "model_fields",
        {
            "optional_int": FakeField(int | None),
            "optional_float": FakeField(float | None),
            "optional_bool": FakeField(bool | None),
            "optional_literal": FakeField(Literal["alpha", "beta"] | None),
            "annotated_optional_int": FakeField(
                Annotated[int | None, "metadata"]
            ),
            "annotated_optional_literal": FakeField(
                Annotated[Literal["one", "two"] | None, "metadata"]
            ),
            "annotated_list": FakeField(Annotated[list[str], "metadata"]),
            "wide_optional": FakeField(int | str | None),
        },
    )

    specs = {
        name: SettingSpec(name, "Server")
        for name in surface.Settings.model_fields
    }

    assert specs["optional_int"].argparse_type is int
    assert specs["optional_float"].argparse_type is float
    assert specs["optional_bool"].argparse_type is str
    assert specs["optional_literal"].argparse_type is str
    assert specs["annotated_optional_int"].argparse_type is int
    assert specs["wide_optional"].argparse_type is str

    assert specs["optional_bool"].choices == ("true", "false")
    assert specs["optional_literal"].choices == ("alpha", "beta")
    assert specs["annotated_optional_literal"].choices == ("one", "two")
    assert specs["annotated_list"].choices is None
    assert specs["wide_optional"].choices is None

    assert specs["optional_bool"].is_bool
    assert not specs["optional_int"].is_bool
    assert specs["optional_int"].is_nullable
    assert specs["annotated_optional_int"].is_nullable
    assert specs["wide_optional"].is_nullable
    assert not specs["annotated_list"].is_nullable


def test_remote_http_transfer_limits_and_config_file_errors(tmp_path):
    assert settings_module._split_csv(None) == []

    with pytest.raises(ValueError, match="must be greater than zero"):
        Settings(remote_http_transfer_threshold_bytes=0)
    with pytest.raises(ValueError, match="must not exceed 4194304"):
        Settings(remote_http_transfer_chunk_bytes=4 * 1024 * 1024 + 1)
    with pytest.raises(
        ValueError, match="must not exceed remote_http_transfer_max"
    ):
        Settings(
            remote_http_transfer_threshold_bytes=2,
            remote_http_transfer_max_spool_bytes=1,
        )

    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        settings_module.read_config_file(missing)
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert settings_module.read_config_file(empty) == {}
