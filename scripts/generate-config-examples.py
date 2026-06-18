#!/usr/bin/env python3
"""Generate config.example.yaml and .env.example from the settings registry."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from local_shell_mcp.config.surface import (
    SECTION_ORDER,
    SETTING_SPECS,
    SettingSpec,
    default_to_string,
    validate_setting_specs,
    yaml_default,
)

DOCKER_ENTRYPOINT_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "DOCKER_RUN_AS_ROOT",
        "false",
        "Run the Dockerized MCP server itself as root. Prefer explicit sudo inside commands instead.",
    ),
    (
        "DOCKER_PERSISTENT_CREDENTIALS",
        "true",
        "Persist GitHub CLI, Git HTTPS credentials, GitCode credentials, SSH keys, .netrc, and GPG state across container rebuilds.",
    ),
    (
        "DOCKER_CREDENTIALS_DIR",
        "/persist/credentials",
        "Root directory for persisted credentials. The Docker Compose example stores it in the local-shell-mcp-credentials volume.",
    ),
    (
        "DOCKER_CHOWN_WORKSPACE",
        "true",
        "chown the mounted workspace to the agent user before starting the server.",
    ),
)

SIDECAR_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "CLOUDFLARE_TUNNEL_TOKEN",
        "",
        "Optional token for the cloudflared tunnel sidecar profile. This uses Cloudflare Tunnel only, not Cloudflare Access.",
    ),
)


def _wrap_comment(text: str, *, width: int = 100) -> list[str]:
    """Wrap a comment into shell/YAML comment lines."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _env_line(name: str, value: Any) -> str:
    return f"{name}={default_to_string(value)}"


def _choices_comment(spec: SettingSpec) -> str | None:
    """Return a comment describing accepted non-boolean values for settings with choices."""
    if spec.is_bool:
        return None
    choices = spec.choices
    if not choices:
        return None
    return f"Choices: {', '.join(choices)}."


def _setting_comment_lines(spec: SettingSpec) -> list[str]:
    """Return wrapped help and choices comment lines for one setting."""
    comments = list(_wrap_comment(spec.help))
    if choices_comment := _choices_comment(spec):
        comments.extend(_wrap_comment(choices_comment))
    return comments


def generate_env_example() -> str:
    """Generate .env.example content."""
    validate_setting_specs()
    lines: list[str] = [
        "# shellcheck shell=sh",
        "# shellcheck disable=SC2034",
        "# Docker Compose uses this file as the main container environment via `env_file: .env`.",
        "# Copy it with: cp .env.example .env",
    ]
    specs_by_section: dict[str, list[SettingSpec]] = {
        section: [] for section in SECTION_ORDER
    }
    for spec in SETTING_SPECS:
        specs_by_section[spec.section].append(spec)

    for section in SECTION_ORDER:
        lines.extend(["", f"# {section}."])
        for spec in specs_by_section[section]:
            for comment in _setting_comment_lines(spec):
                lines.append(f"# {comment}")
            lines.append(_env_line(spec.env_var, spec.default))

    lines.extend(
        [
            "",
            "# Docker entrypoint settings. These are read before local-shell-mcp starts.",
        ]
    )
    for name, default, help_text in DOCKER_ENTRYPOINT_SPECS:
        for comment in _wrap_comment(help_text):
            lines.append(f"# {comment}")
        lines.append(f"{name}={default}")

    lines.extend(["", "# Optional sidecar settings."])
    for name, default, help_text in SIDECAR_SPECS:
        for comment in _wrap_comment(help_text):
            lines.append(f"# {comment}")
        lines.append(f"{name}={default}")

    return "\n".join(lines) + "\n"


def _yaml_string(value: str) -> str:
    """Render a string as a quoted YAML scalar, preserving spaces exactly."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_scalar(value: Any) -> str:
    """Render a scalar/list default as simple YAML while preserving string details."""
    value = yaml_default(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        rendered = "\n"
        for item in value:
            rendered += f"  - {_yaml_string(str(item))}\n"
        return rendered.rstrip()
    return _yaml_string(str(value))


def generate_yaml_example() -> str:
    """Generate config.example.yaml content."""
    validate_setting_specs()
    lines: list[str] = [
        "# Full YAML config example.",
        "# Effective precedence: defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments.",
    ]
    specs_by_section = {section: [] for section in SECTION_ORDER}
    for spec in SETTING_SPECS:
        specs_by_section[spec.section].append(spec)

    for section in SECTION_ORDER:
        lines.extend(["", f"# {section}."])
        for spec in specs_by_section[section]:
            for comment in _setting_comment_lines(spec):
                lines.append(f"# {comment}")
            value = _yaml_scalar(spec.default)
            if "\n" in value:
                lines.append(f"{spec.name}:{value}")
            else:
                lines.append(f"{spec.name}: {value}")

    return "\n".join(lines) + "\n"


def _jsonable_default(value: Any) -> Any:
    """Render a default value for generated JSON docs."""
    value = yaml_default(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _markdown_escape(value: Any) -> str:
    """Escape compact Markdown table cell text."""
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text.replace("|", "\\|")


def _display_default(value: Any) -> str:
    """Return a user-facing default value for reference tables."""
    rendered = default_to_string(value)
    return "unset" if rendered == "" else rendered


def _type_label(spec: SettingSpec) -> str:
    """Return a compact type or choice label for a setting."""
    if spec.choices:
        return " | ".join(spec.choices)
    annotation = spec.non_none_annotation
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is Path:
        return "path"
    if str(annotation) == "list[str]":
        return "CSV or YAML list"
    return "string"


def _setting_doc(spec: SettingSpec) -> dict[str, Any]:
    """Return one setting record for generated configuration reference JSON."""
    return {
        "name": spec.name,
        "section": spec.section,
        "cli": spec.cli_flag,
        "unset_cli": spec.unset_cli_flag if spec.is_nullable else None,
        "env": spec.env_var,
        "default": _jsonable_default(spec.default),
        "default_display": _display_default(spec.default),
        "type": _type_label(spec),
        "choices": list(spec.choices or []),
        "nullable": spec.is_nullable,
        "description": spec.help,
    }


def generate_config_reference_json() -> str:
    """Generate machine-readable configuration reference JSON."""
    validate_setting_specs()
    payload = {
        "precedence": [
            "defaults",
            "config file",
            "LOCAL_SHELL_MCP_* environment variables",
            "CLI arguments",
        ],
        "settings": [_setting_doc(spec) for spec in SETTING_SPECS],
        "docker_entrypoint_settings": [
            {"env": name, "default": default, "description": help_text}
            for name, default, help_text in DOCKER_ENTRYPOINT_SPECS
        ],
        "sidecar_settings": [
            {"env": name, "default": default, "description": help_text}
            for name, default, help_text in SIDECAR_SPECS
        ],
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def _config_row(setting: dict[str, Any]) -> str:
    """Render one Markdown table row for an application setting."""
    cli = f"`{setting['cli']}`"
    if setting["unset_cli"]:
        cli += f"<br>`{setting['unset_cli']}` clears the value"
    return (
        "| {name} | {cli} | `{env}` | {type_} | `{default}` | {desc} |".format(
            name=f"`{_markdown_escape(setting['name'])}`",
            cli=cli,
            env=_markdown_escape(setting["env"]),
            type_=_markdown_escape(setting["type"]),
            default=_markdown_escape(setting["default_display"]),
            desc=_markdown_escape(setting["description"]),
        )
    )


def _env_row(env: str, default: str, description: str) -> str:
    """Render one Markdown table row for an environment-only setting."""
    display_default = default if default else "unset"
    return (
        f"| `{_markdown_escape(env)}` | `{_markdown_escape(display_default)}` "
        f"| {_markdown_escape(description)} |"
    )


def generate_config_reference_markdown() -> str:
    """Generate the configuration reference Markdown page."""
    validate_setting_specs()
    settings = [_setting_doc(spec) for spec in SETTING_SPECS]
    lines = [
        "# Configuration reference",
        "",
        "<!-- Generated by scripts/generate-config-examples.py. Do not edit by hand. -->",
        "",
        "This page is generated from the application settings registry. Regenerate it when `Settings` or `SETTING_SPECS` changes.",
        "",
        "Machine-readable configuration metadata is committed at [`generated/configuration.json`](generated/configuration.json). Complete copy-editable examples are committed at the repository root as `.env.example` and `config.example.yaml`.",
        "",
        "Settings resolve in this order:",
        "",
        "```text",
        "defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments",
        "```",
        "",
        "YAML config files use flat setting names such as `auth_mode` and `workspace_root`. Nested groups are not read by the application settings loader.",
        "",
        "`audit_log_path` and `agent_config_dir` are derived from `state_dir` as `audit_log/audit.jsonl` and `agent_config`; they are not standalone settings.",
        "",
    ]
    for section in SECTION_ORDER:
        grouped = [
            setting for setting in settings if setting["section"] == section
        ]
        if not grouped:
            continue
        lines.extend(
            [
                f"## {section}",
                "",
                "| Setting | CLI | Environment | Type | Default | Description |",
                "|---|---|---|---|---:|---|",
            ]
        )
        lines.extend(_config_row(setting) for setting in grouped)
        lines.append("")
    lines.extend(
        [
            "## Docker entrypoint settings",
            "",
            "These variables are consumed by the Docker entrypoint before the Python application starts.",
            "",
            "| Environment | Default | Description |",
            "|---|---:|---|",
        ]
    )
    lines.extend(_env_row(*item) for item in DOCKER_ENTRYPOINT_SPECS)
    lines.extend(
        [
            "",
            "## Optional sidecar settings",
            "",
            "| Environment | Default | Description |",
            "|---|---:|---|",
        ]
    )
    lines.extend(_env_row(*item) for item in SIDECAR_SPECS)
    lines.append("")
    return "\n".join(lines)


def write_examples(*, check: bool) -> int:
    """Write generated files or check they are up to date."""
    root = Path(__file__).resolve().parents[1]
    outputs = {
        root / ".env.example": generate_env_example(),
        root / "config.example.yaml": generate_yaml_example(),
        root
        / "docs/reference/generated/configuration.json": generate_config_reference_json(),
        root
        / "docs/reference/configuration.md": generate_config_reference_markdown(),
    }
    stale: list[Path] = []
    for path, content in outputs.items():
        if check:
            if path.read_text() != content:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        for path in stale:
            print(f"out of date: {path.relative_to(root)}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated examples are stale",
    )
    args = parser.parse_args()
    return write_examples(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
