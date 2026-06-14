import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import local_shell_mcp.config.surface as surface
from local_shell_mcp.config.settings import Settings, load_settings
from local_shell_mcp.config.surface import (
    SETTING_SPECS,
    argparse_choices_for,
    argparse_type_for,
    is_bool_setting,
    is_nullable_setting,
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


def test_generated_yaml_example_loads_without_losing_defaults(monkeypatch):
    for spec in SETTING_SPECS:
        monkeypatch.delenv(spec.env_var, raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_CONFIG", raising=False)

    settings = load_settings("config.example.yaml", create_dirs=False)
    defaults = Settings()

    assert settings.command_denylist == defaults.command_denylist
    assert settings.path_denylist == defaults.path_denylist
    assert settings.allow_full_container == defaults.allow_full_container


def test_typing_helpers_cover_current_setting_shapes():
    assert argparse_type_for("port") is int
    assert argparse_type_for("public_tool_timeout_s") is float
    assert argparse_type_for("host") is str
    assert argparse_type_for("public_base_url") is str

    assert argparse_choices_for("mode") == ("mcp", "http", "both", "stdio")
    assert argparse_choices_for("allow_network") == ("true", "false")
    assert argparse_choices_for("host") is None

    assert is_bool_setting("allow_network")
    assert not is_bool_setting("public_base_url")
    assert is_nullable_setting("public_base_url")
    assert not is_nullable_setting("command_denylist")


def test_typing_helpers_cover_future_nullable_shapes(monkeypatch):
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

    assert argparse_type_for("optional_int") is int
    assert argparse_type_for("optional_float") is float
    assert argparse_type_for("optional_bool") is str
    assert argparse_type_for("optional_literal") is str
    assert argparse_type_for("annotated_optional_int") is int
    assert argparse_type_for("wide_optional") is str

    assert argparse_choices_for("optional_bool") == ("true", "false")
    assert argparse_choices_for("optional_literal") == ("alpha", "beta")
    assert argparse_choices_for("annotated_optional_literal") == ("one", "two")
    assert argparse_choices_for("annotated_list") is None
    assert argparse_choices_for("wide_optional") is None

    assert is_bool_setting("optional_bool")
    assert not is_bool_setting("optional_int")
    assert is_nullable_setting("optional_int")
    assert is_nullable_setting("annotated_optional_int")
    assert is_nullable_setting("wide_optional")
    assert not is_nullable_setting("annotated_list")
