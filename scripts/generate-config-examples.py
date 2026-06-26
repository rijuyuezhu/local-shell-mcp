#!/usr/bin/env python3
"""Generate config examples and configuration reference JSON."""

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
        "DOCKER_AGENT_UID",
        "",
        "Optional UID for the agent user at container startup. Leave empty to auto-detect the mounted workspace owner; set explicitly to override.",
    ),
    (
        "DOCKER_AGENT_GID",
        "",
        "Optional GID for the agent user at container startup. Leave empty to auto-detect the mounted workspace owner; set explicitly to override.",
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


def _code(value: Any) -> dict[str, str]:
    """Return a generic renderer code-cell value."""
    return {"code": str(value)}


def _setting_row(spec: SettingSpec) -> list[Any]:
    """Return one generic renderer row for a setting."""
    cli_lines: list[Any] = [_code(spec.cli_flag)]
    if spec.is_nullable:
        cli_lines.append(_code(f"{spec.unset_cli_flag} clears the value"))
    return [
        _code(spec.name),
        {"lines": cli_lines},
        _code(spec.env_var),
        _type_label(spec),
        _code(_display_default(spec.default)),
        spec.help,
    ]


def _settings_sections() -> list[dict[str, Any]]:
    """Return generic renderer sections for configuration settings."""
    sections: list[dict[str, Any]] = []
    for section in SECTION_ORDER:
        rows = [
            _setting_row(spec)
            for spec in SETTING_SPECS
            if spec.section == section
        ]
        if rows:
            sections.append(
                {
                    "kind": "table",
                    "heading": section,
                    "headers": [
                        "Setting",
                        "CLI",
                        "Environment",
                        "Type",
                        "Default",
                        "Description",
                    ],
                    "rows": rows,
                }
            )
    sections.append(
        {
            "kind": "table",
            "heading": "Docker entrypoint settings",
            "body": "These variables are consumed by the Docker entrypoint before the Python application starts.",
            "headers": ["Environment", "Default", "Description"],
            "rows": [
                [_code(name), _code(default or "unset"), help_text]
                for name, default, help_text in DOCKER_ENTRYPOINT_SPECS
            ],
        }
    )
    sections.append(
        {
            "kind": "table",
            "heading": "Optional sidecar settings",
            "headers": ["Environment", "Default", "Description"],
            "rows": [
                [_code(name), _code(default or "unset"), help_text]
                for name, default, help_text in SIDECAR_SPECS
            ],
        }
    )
    return sections


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
        "section_order": list(SECTION_ORDER),
        "settings": [_setting_doc(spec) for spec in SETTING_SPECS],
        "docker_entrypoint_settings": [
            {"env": name, "default": default, "description": help_text}
            for name, default, help_text in DOCKER_ENTRYPOINT_SPECS
        ],
        "sidecar_settings": [
            {"env": name, "default": default, "description": help_text}
            for name, default, help_text in SIDECAR_SPECS
        ],
        "sections": _settings_sections(),
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def write_examples(*, check: bool) -> int:
    """Write generated files or check they are up to date."""
    root = Path(__file__).resolve().parents[1]
    outputs = {
        root / ".env.example": generate_env_example(),
        root / "config.example.yaml": generate_yaml_example(),
        root
        / "docs/reference/generated/configuration.json": generate_config_reference_json(),
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
