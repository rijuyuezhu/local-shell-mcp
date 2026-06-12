"""Backward-compatible imports for the configuration surface registry."""

from __future__ import annotations

from .surface import (
    SECTION_ORDER,
    SETTING_SPECS,
    SETTING_SPECS_BY_SECTION,
    SPECS_BY_NAME,
    BoolChoiceAction,
    SectionName,
    SettingSpec,
    SpecBySection,
    argparse_choices_for,
    argparse_type_for,
    cli_overrides_from_args,
    default_to_string,
    default_value,
    is_bool_setting,
    register_setting_cli_args,
    validate_setting_specs,
    yaml_default,
)

__all__ = [
    "SECTION_ORDER",
    "SETTING_SPECS",
    "SETTING_SPECS_BY_SECTION",
    "SPECS_BY_NAME",
    "BoolChoiceAction",
    "SectionName",
    "SettingSpec",
    "SpecBySection",
    "argparse_choices_for",
    "argparse_type_for",
    "cli_overrides_from_args",
    "default_to_string",
    "default_value",
    "is_bool_setting",
    "register_setting_cli_args",
    "validate_setting_specs",
    "yaml_default",
]
