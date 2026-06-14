"""Central registry for runtime configuration surfaces.

Settings field docstrings are the source of truth for application setting help
text; this registry controls grouping, CLI flags, and generated example
configuration files.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args, get_origin

from .settings import ENV_PREFIX, Settings

type SectionName = Literal[
    "Server",
    "Paths and state",
    "Authentication and OAuth",
    "Safety and resource limits",
    "Remote workers",
    "Agent capability bridge",
    "Tool executables",
]

SECTION_ORDER: tuple[SectionName, ...] = get_args(SectionName.__value__)
CLI_UNSET = object()


@dataclass(frozen=True)
class SettingSpec:
    """Metadata for one application setting covered by env, YAML, and CLI."""

    name: str
    """Settings attribute name on the Settings model."""
    section: SectionName
    """Documentation and config-file section where this setting is grouped."""
    help_override: str | None = None
    """Optional explicit help text; Settings field descriptions are used by default."""
    metavar: str | None = None
    """Optional placeholder shown for CLI arguments that take values."""
    example_default: Any | None = None
    """Optional value used when rendering example configuration files."""

    @property
    def help(self) -> str:
        """Return human-readable help text used by CLI and generated examples."""
        if self.help_override is not None:
            return self.help_override
        description = Settings.model_fields[self.name].description
        if description:
            return description
        raise RuntimeError(f"Missing Settings field docstring for {self.name}")

    @property
    def env_var(self) -> str:
        """Return the LOCAL_SHELL_MCP_* variable for this setting."""
        return f"{ENV_PREFIX}{self.name.upper()}"

    @property
    def cli_flag(self) -> str:
        """Return the canonical CLI flag for this setting."""
        return f"--{self.name.replace('_', '-')}"

    @property
    def unset_cli_flag(self) -> str:
        """Return the CLI flag that explicitly unsets this setting."""
        return f"--unset-{self.name.replace('_', '-')}"


SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("mode", "Server"),
    SettingSpec("host", "Server", metavar="HOST"),
    SettingSpec("port", "Server", metavar="PORT"),
    SettingSpec("workspace_root", "Paths and state", metavar="PATH"),
    SettingSpec("state_dir", "Paths and state", metavar="PATH"),
    SettingSpec("audit_log_path", "Paths and state", metavar="PATH"),
    SettingSpec("auth_mode", "Authentication and OAuth", metavar="MODE"),
    SettingSpec("auth_bypass_localhost", "Authentication and OAuth"),
    SettingSpec("require_auth_for_mcp_discovery", "Authentication and OAuth"),
    SettingSpec("public_base_url", "Authentication and OAuth", metavar="URL"),
    SettingSpec("oauth_issuer", "Authentication and OAuth", metavar="URL"),
    SettingSpec(
        "oauth_resource",
        "Authentication and OAuth",
        metavar="URL",
    ),
    SettingSpec("oauth_admin_pin", "Authentication and OAuth", metavar="PIN"),
    SettingSpec(
        "oauth_access_token_ttl_s",
        "Authentication and OAuth",
        metavar="SECONDS",
    ),
    SettingSpec(
        "oauth_code_ttl_s",
        "Authentication and OAuth",
        metavar="SECONDS",
    ),
    SettingSpec("allow_full_container", "Safety and resource limits"),
    SettingSpec("allow_network", "Safety and resource limits"),
    SettingSpec("relaxed_client_tool_hints", "Safety and resource limits"),
    SettingSpec(
        "public_tool_timeout_s", "Safety and resource limits", metavar="SECONDS"
    ),
    SettingSpec(
        "public_run_shell_default_timeout_s",
        "Safety and resource limits",
        metavar="SECONDS",
    ),
    SettingSpec(
        "public_run_shell_max_timeout_s",
        "Safety and resource limits",
        metavar="SECONDS",
    ),
    SettingSpec(
        "internal_shell_default_timeout_s",
        "Safety and resource limits",
        metavar="SECONDS",
    ),
    SettingSpec(
        "internal_shell_max_timeout_s",
        "Safety and resource limits",
        metavar="SECONDS",
    ),
    SettingSpec(
        "max_output_bytes", "Safety and resource limits", metavar="BYTES"
    ),
    SettingSpec(
        "max_file_read_bytes", "Safety and resource limits", metavar="BYTES"
    ),
    SettingSpec(
        "max_file_write_bytes", "Safety and resource limits", metavar="BYTES"
    ),
    SettingSpec(
        "max_grep_results", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "max_directory_entries", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "max_glob_results", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "max_tree_entries", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "max_read_many_files", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "max_read_many_total_bytes",
        "Safety and resource limits",
        metavar="BYTES",
    ),
    SettingSpec("max_todos", "Safety and resource limits", metavar="COUNT"),
    SettingSpec(
        "max_todo_bytes", "Safety and resource limits", metavar="BYTES"
    ),
    SettingSpec(
        "max_audit_log_bytes", "Safety and resource limits", metavar="BYTES"
    ),
    SettingSpec("max_tmp_files", "Safety and resource limits", metavar="COUNT"),
    SettingSpec("max_tmp_bytes", "Safety and resource limits", metavar="BYTES"),
    SettingSpec(
        "max_concurrent_commands", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "max_tmux_sessions", "Safety and resource limits", metavar="COUNT"
    ),
    SettingSpec(
        "command_denylist", "Safety and resource limits", metavar="CSV"
    ),
    SettingSpec("path_denylist", "Safety and resource limits", metavar="CSV"),
    SettingSpec("remote_enabled", "Remote workers"),
    SettingSpec("remote_invite_ttl_s", "Remote workers", metavar="SECONDS"),
    SettingSpec("remote_poll_timeout_s", "Remote workers", metavar="SECONDS"),
    SettingSpec("remote_job_timeout_s", "Remote workers", metavar="SECONDS"),
    SettingSpec("agent_bridge_enabled", "Agent capability bridge"),
    SettingSpec("agent_config_dir", "Agent capability bridge", metavar="PATH"),
    SettingSpec(
        "agent_mcp_probe_timeout_s",
        "Agent capability bridge",
        metavar="SECONDS",
    ),
    SettingSpec(
        "agent_mcp_call_timeout_s", "Agent capability bridge", metavar="SECONDS"
    ),
    SettingSpec("agent_dynamic_mcp_tools", "Agent capability bridge"),
    SettingSpec("agent_dynamic_skill_tools", "Agent capability bridge"),
    SettingSpec("shell_executable", "Tool executables", metavar="PATH"),
    SettingSpec("tmux_bin", "Tool executables", metavar="PATH"),
    SettingSpec("rg_bin", "Tool executables", metavar="PATH"),
    SettingSpec("python_bin", "Tool executables", metavar="PATH"),
)

type SpecBySection = list[tuple[SectionName, list[SettingSpec]]]


def _group_setting_specs_by_section() -> SpecBySection:
    """Group setting specs by section while preserving registry order within each section."""
    specs_by_section: dict[SectionName, list[SettingSpec]] = {
        section: [] for section in SECTION_ORDER
    }
    for spec in SETTING_SPECS:
        specs_by_section[spec.section].append(spec)
    return [(section, specs_by_section[section]) for section in SECTION_ORDER]


SETTING_SPECS_BY_SECTION: SpecBySection = _group_setting_specs_by_section()
SPECS_BY_NAME: dict[str, SettingSpec] = {
    spec.name: spec for spec in SETTING_SPECS
}


def validate_setting_specs() -> None:
    """Ensure every Settings field has exactly one registry entry."""
    fields = set(Settings.model_fields)
    specs = set(SPECS_BY_NAME)
    missing = sorted(fields - specs)
    extra = sorted(specs - fields)
    if missing or extra:
        raise RuntimeError(
            f"Setting spec mismatch: missing={missing}, extra={extra}"
        )


def default_value(name: str) -> Any:
    """Return the concrete default for a Settings field."""
    if (spec := SPECS_BY_NAME.get(name)) and spec.example_default is not None:
        return spec.example_default
    field = Settings.model_fields[name]
    return field.get_default(call_default_factory=True)


def default_to_string(value: Any) -> str:
    """Render a default value for documentation, .env files, and argparse help."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        items = cast(list[Any], value)
        return ",".join(str(item) for item in items)
    return str(value)


def yaml_default(value: Any) -> Any:
    """Render a default value suitable for YAML dumping."""
    if isinstance(value, Path):
        return str(value)
    return value


def _setting_annotation(name: str) -> Any:
    """Return a Settings field annotation after unwrapping Annotated."""
    annotation = Settings.model_fields[name].annotation
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


def _non_none_annotation(name: str) -> Any:
    """Return a Settings field annotation with an optional None member removed."""
    annotation = _setting_annotation(name)
    args = get_args(annotation)
    if type(None) not in args:
        return annotation
    non_none_args = tuple(arg for arg in args if arg is not type(None))
    if len(non_none_args) == 1:
        return non_none_args[0]
    return annotation


def argparse_type_for(name: str) -> type[int] | type[float] | type[str]:
    """Return an argparse type callable for a Settings field."""
    annotation = _non_none_annotation(name)
    if annotation is int:
        return int
    if annotation is float:
        return float
    return str


def argparse_choices_for(name: str) -> tuple[str, ...] | None:
    """Return argparse choices for Literal settings."""
    annotation = _non_none_annotation(name)
    if get_origin(annotation) is Literal:
        return tuple(str(item) for item in get_args(annotation))
    elif is_bool_setting(name):
        return ("true", "false")
    return None


def is_bool_setting(name: str) -> bool:
    """Return whether a Settings field is boolean."""
    return _non_none_annotation(name) is bool


def is_nullable_setting(name: str) -> bool:
    """Return whether a Settings field accepts None as a concrete value."""
    return type(None) in get_args(_setting_annotation(name))


class BoolChoiceAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        if values not in ("true", "false"):
            raise argparse.ArgumentTypeError(f"Invalid boolean value: {values}")
        setattr(namespace, self.dest, values == "true")


def register_setting_cli_args(parser: argparse.ArgumentParser) -> None:
    """Register one CLI option for every Settings field, grouped by section."""
    validate_setting_specs()
    for section, specs in SETTING_SPECS_BY_SECTION:
        group = parser.add_argument_group(section)
        for spec in specs:
            kwargs: dict[str, Any] = {
                "dest": spec.name,
                "default": CLI_UNSET,
                "help": f"{spec.help} Overrides {spec.env_var} and config files. Default: {default_to_string(default_value(spec.name)) or 'unset'}.",
            }
            if spec.metavar:
                kwargs["metavar"] = spec.metavar
            choices = argparse_choices_for(spec.name)
            if choices:
                kwargs["choices"] = choices

            if (argparse_type := argparse_type_for(spec.name)) in (int, float):
                kwargs["type"] = argparse_type
            elif is_bool_setting(spec.name):
                kwargs["action"] = BoolChoiceAction

            target = group
            if is_nullable_setting(spec.name):
                target = group.add_mutually_exclusive_group()
            target.add_argument(spec.cli_flag, **kwargs)
            if is_nullable_setting(spec.name):
                target.add_argument(
                    spec.unset_cli_flag,
                    action="store_const",
                    const=None,
                    default=CLI_UNSET,
                    dest=spec.name,
                    help=(
                        f"Clear {spec.name.replace('_', '-')} by setting it to "
                        f"null. Overrides {spec.env_var} and config files."
                    ),
                )


def cli_overrides_from_args(args: argparse.Namespace) -> dict[str, object]:
    """Collect explicit CLI server options as Settings field overrides."""
    validate_setting_specs()
    return {
        spec.name: value
        for spec in SETTING_SPECS
        if (value := getattr(args, spec.name, CLI_UNSET)) is not CLI_UNSET
    }
