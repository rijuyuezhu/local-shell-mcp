import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import local_shell_mcp.config.surface as surface
from local_shell_mcp.config.settings import Settings, load_settings
from local_shell_mcp.config.surface import (
    SETTING_SPECS,
    SPECS_BY_NAME,
    SettingSpec,
    validate_setting_specs,
)


@dataclass(frozen=True)
class FakeField:
    annotation: Any


def test_setting_specs_cover_settings_fields():
    validate_setting_specs()


def test_generated_config_examples_are_current():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/generate-config-examples.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_config_examples_include_every_registered_setting():
    env_example = Path(".env.example").read_text()
    yaml_example = Path("config.example.yaml").read_text()

    for spec in SETTING_SPECS:
        assert re.search(rf"^{spec.env_var}=", env_example, flags=re.MULTILINE)
        assert re.search(rf"^{spec.name}:", yaml_example, flags=re.MULTILINE)
        for word in spec.help.split():
            assert word in env_example
            assert word in yaml_example


def test_generated_config_examples_document_non_bool_choices_only():
    env_example = Path(".env.example").read_text()
    yaml_example = Path("config.example.yaml").read_text()

    for example in (env_example, yaml_example):
        assert "# Choices: mcp, http, both, stdio." in example
        assert "# Choices: none, oauth." in example
        assert "# Choices: true, false." not in example


def test_generated_yaml_example_loads_without_losing_defaults(monkeypatch):
    for spec in SETTING_SPECS:
        monkeypatch.delenv(spec.env_var, raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_CONFIG", raising=False)

    settings = load_settings("config.example.yaml", create_dirs=False)
    defaults = Settings()

    assert settings.command_denylist == defaults.command_denylist
    assert settings.path_denylist == defaults.path_denylist
    assert settings.allow_full_container == defaults.allow_full_container


def test_setting_spec_properties_cover_current_setting_shapes():
    assert SPECS_BY_NAME["port"].argparse_type is int
    assert SPECS_BY_NAME["public_tool_timeout_s"].argparse_type is float
    assert SPECS_BY_NAME["host"].argparse_type is str
    assert SPECS_BY_NAME["public_base_url"].argparse_type is str

    assert SPECS_BY_NAME["mode"].choices == ("mcp", "http", "both", "stdio")
    assert SPECS_BY_NAME["allow_network"].choices == ("true", "false")
    assert SPECS_BY_NAME["host"].choices is None

    assert SPECS_BY_NAME["allow_network"].is_bool
    assert not SPECS_BY_NAME["public_base_url"].is_bool
    assert SPECS_BY_NAME["public_base_url"].is_nullable
    assert not SPECS_BY_NAME["command_denylist"].is_nullable


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
