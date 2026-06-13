"""Load, normalize, and validate runtime settings for workspace boundaries, authentication, tools, and remote workers."""

import os
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_WORKSPACE_ROOT = Path("/workspace")
DEFAULT_STATE_DIR = DEFAULT_WORKSPACE_ROOT / ".local-shell-mcp"
DEFAULT_AUDIT_LOG_PATH = DEFAULT_STATE_DIR / "audit.jsonl"
DEFAULT_AGENT_CONFIG_DIR = Path("/home/agent/local-shell-mcp-config")
ENV_PREFIX = "LOCAL_SHELL_MCP_"

SENSITIVE_SETTING_KEYS = {
    "oauth_admin_pin",
}


def _split_csv(value: str | list[str] | None) -> list[str]:
    """Normalize comma-delimited environment values into trimmed non-empty items."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    """Runtime settings.

    Environment variables use the LOCAL_SHELL_MCP_ prefix. Optional YAML config can
    be supplied with --config or LOCAL_SHELL_MCP_CONFIG. Effective precedence is:
    defaults < config file < environment variables < CLI overrides.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, extra="ignore", use_attribute_docstrings=True
    )

    host: str = "0.0.0.0"
    """Bind host for HTTP/MCP transports."""
    port: int = 8765
    """Bind port for HTTP/MCP transports."""
    mode: Literal["mcp", "http", "both", "stdio"] = "mcp"
    """Server transport mode."""

    workspace_root: Path = DEFAULT_WORKSPACE_ROOT
    """Root directory for normal file and command operations."""
    audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH
    """Path to the JSONL audit log."""
    state_dir: Path = DEFAULT_STATE_DIR
    """Directory for runtime state such as audit logs and temporary files."""

    # By default, tools are limited to workspace_root. Set true only inside a disposable container.
    allow_full_container: bool = False
    """Disable built-in workspace and command restrictions; use only in disposable containers or VMs."""
    allow_network: bool = True
    """Allow network-capable operations."""
    # Client-facing hint only: reduces MCP client confirmations for local tools
    # without changing server-side authentication, authorization, or command policy.
    relaxed_client_tool_hints: bool = False
    """Advertise lower-risk MCP client hints for local tools without changing server-side authentication or command policy."""

    # Public MCP/HTTP tool calls are guarded separately from internal command execution.
    public_tool_timeout_s: float = 60
    """Public MCP/HTTP tool watchdog timeout in seconds."""
    public_run_shell_default_timeout_s: int = 10
    """Default timeout for public run_shell_tool calls in seconds."""
    public_run_shell_max_timeout_s: int = 60
    """Maximum timeout accepted by public run_shell_tool calls in seconds."""
    internal_shell_default_timeout_s: int = 60
    """Advanced internal shell command default timeout in seconds; public run_shell_tool uses stricter public settings."""
    internal_shell_max_timeout_s: int = 3600
    """Advanced internal shell command maximum timeout in seconds; public run_shell_tool uses stricter public settings."""
    max_output_bytes: int = 200_000
    """Command output truncation limit in bytes."""
    max_file_read_bytes: int = 512_000
    """Per-file read limit in bytes."""
    max_file_write_bytes: int = 5_000_000
    """Per-file write/edit limit in bytes."""
    max_grep_results: int = 200
    """Maximum grep result count."""
    max_directory_entries: int = 5_000
    """Maximum listed directory entries."""
    max_glob_results: int = 5_000
    """Maximum glob search results."""
    max_tree_entries: int = 5_000
    """Maximum tree-view entries."""
    max_read_many_files: int = 100
    """Maximum files read by a multi-file read operation."""
    max_read_many_total_bytes: int = 5_000_000
    """Combined byte limit for multi-file reads."""
    max_todos: int = 1_000
    """Todo-list item limit."""
    max_todo_bytes: int = 1_000_000
    """Todo-list serialized byte limit."""
    max_audit_log_bytes: int = 20_000_000
    """Audit-log rotation threshold in bytes."""
    max_tmp_files: int = 500
    """Temporary-file count limit."""
    max_tmp_bytes: int = 50_000_000
    """Temporary-file byte limit."""
    max_concurrent_commands: int = 4
    """Concurrent command limit."""
    max_tmux_sessions: int = 16
    """Persistent shell session limit."""

    # Remote worker mode is enabled by default. Remote machines join with one-time
    # invites, poll for jobs over outbound HTTP(S), and expose near-parity tools.
    remote_enabled: bool = True
    """Enable remote worker routes and MCP tools."""
    remote_invite_ttl_s: int = 600
    """One-time remote worker invite lifetime in seconds."""
    remote_poll_timeout_s: int = 25
    """Remote worker long-poll heartbeat timeout in seconds."""
    remote_job_timeout_s: int = 3600
    """Control-side remote job result timeout in seconds."""

    # Agent capability bridge. External sync tools write normalized MCP and skill
    # config here; local-shell-mcp reads it without mutating it.
    agent_bridge_enabled: bool = True
    """Enable agent capability bridge tools."""
    agent_config_dir: Path = DEFAULT_AGENT_CONFIG_DIR
    """Read-only capability config directory."""
    agent_mcp_probe_timeout_s: int = 5
    """Agent MCP server probe timeout in seconds."""
    agent_mcp_call_timeout_s: int = 60
    """Agent MCP tool-call timeout in seconds."""
    agent_dynamic_mcp_tools: bool = True
    """Register dynamic MCP bridge tools."""
    agent_dynamic_skill_tools: bool = True
    """Register dynamic skill bridge tools."""

    shell_executable: str = "/bin/bash"
    """Shell executable used for shell commands."""
    tmux_bin: str = "tmux"
    """tmux executable."""
    rg_bin: str = "rg"
    """ripgrep executable."""
    python_bin: str = "python3"
    """Python executable."""

    # Authentication. OAuth is the default for ChatGPT custom connectors.
    auth_mode: Literal["none", "oauth"] = "oauth"
    """Authentication mode: oauth or none. Do not expose public services with none."""
    auth_bypass_localhost: bool = True
    """Allow localhost requests without bearer authentication."""
    # MCP-over-HTTP requests are protected by default; only OAuth/bootstrap
    # metadata routes stay public. Kept for backwards-compatible config parsing.
    require_auth_for_mcp_discovery: bool = True
    """Require bearer auth for MCP-over-HTTP requests; OAuth/bootstrap routes remain public."""

    # Built-in OAuth 2.1 authorization server for ChatGPT MCP connectors.
    # Set public_base_url to the externally reachable HTTPS origin, e.g. https://local-shell-mcp.example.com
    public_base_url: str | None = None
    """Public HTTPS origin used in OAuth metadata and callbacks."""
    oauth_issuer: str | None = None
    """Advanced compatibility override for OAuth issuer metadata; usually derived from public_base_url."""
    oauth_resource: str | None = None
    """Advanced compatibility override for OAuth resource metadata; usually derived from public_base_url plus /mcp."""
    oauth_admin_pin: str | None = None
    """PIN required to approve OAuth authorization."""
    # Keep the embedded single-user authorization flow simple, but avoid
    # issuing permanent bearer tokens by default.
    oauth_access_token_ttl_s: int = 3600
    """Advanced bearer token lifetime in seconds."""
    oauth_code_ttl_s: int = 300
    """Advanced OAuth authorization-code lifetime in seconds."""

    # Command policy. Set denylist empty if this container is intentionally disposable.
    command_denylist: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "docker.sock",
            "/var/run/docker.sock",
            "mkfs",
            "mount",
            "umount",
            "shutdown",
            "reboot",
            "systemctl",
            "iptables",
            "nft",
        ]
    )
    """Comma-separated command denylist in env/CLI, or a YAML list in config files. Cleared when full-container mode is enabled."""
    path_denylist: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            ".ssh/id_rsa",
            ".ssh/id_ed25519",
            ".env",
            "secrets",
            "credentials",
            ".git/config",
        ]
    )
    """Comma-separated path denylist in env/CLI, or a YAML list in config files. Cleared when full-container mode is enabled."""

    @field_validator(
        "workspace_root",
        "audit_log_path",
        "state_dir",
        "agent_config_dir",
        mode="before",
    )
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        """Expand user and environment variables for path settings before validation."""
        expanded = os.path.expandvars(os.path.expanduser(str(value)))
        return Path(os.path.abspath(expanded))

    @field_validator("command_denylist", "path_denylist", mode="before")
    @classmethod
    def split_csv_fields(cls, value: str | list[str] | None) -> list[str]:
        """Normalize comma-delimited restriction lists supplied through environment variables."""
        return _split_csv(value)

    @model_validator(mode="after")
    def disable_builtin_restrictions_in_full_container_mode(self) -> Settings:
        """Remove built-in command and path restrictions when full-container mode is explicitly enabled."""
        if self.allow_full_container:
            self.command_denylist = []
            self.path_denylist = []
        return self

    def with_workspace_relative_defaults(self) -> Settings:
        """Resolve state and audit paths relative to the workspace when they were left at defaults."""
        if self.workspace_root == DEFAULT_WORKSPACE_ROOT:
            return self

        updates: dict[str, Path] = {}
        if self.state_dir == DEFAULT_STATE_DIR:
            updates["state_dir"] = self.workspace_root / ".local-shell-mcp"
        if self.audit_log_path == DEFAULT_AUDIT_LOG_PATH:
            state_dir = updates.get("state_dir", self.state_dir)
            updates["audit_log_path"] = state_dir / "audit.jsonl"

        if not updates:
            return self
        return self.model_copy(update=updates)


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten one level of grouped YAML keys into Settings field names."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            nested = cast(dict[str, Any], value)
            for child_key, child_value in nested.items():
                flat[f"{key}_{child_key}"] = child_value
        else:
            flat[key] = value
    return flat


def read_config_file(path: str | Path | None) -> dict[str, Any]:
    """Read optional YAML configuration values."""
    if not path:
        return {}
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(config_path)
    loaded = yaml.safe_load(config_path.read_text())
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a mapping: {config_path}")
    return _flatten_config(cast(dict[str, Any], loaded))


def _env_overrides() -> dict[str, Any]:
    """Return settings explicitly present in the process environment."""
    present = {
        name: field_name
        for field_name in Settings.model_fields
        if (name := f"{ENV_PREFIX}{field_name.upper()}") in os.environ
    }
    if not present:
        return {}
    env_settings = Settings()
    return {
        field_name: getattr(env_settings, field_name)
        for field_name in present.values()
    }


def _prepare_settings(settings: Settings, *, create_dirs: bool) -> Settings:
    """Apply derived defaults and create runtime directories when requested."""
    settings = settings.with_workspace_relative_defaults()
    if create_dirs:
        settings.workspace_root.mkdir(parents=True, exist_ok=True)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def load_settings(
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    *,
    create_dirs: bool = True,
) -> Settings:
    """Load settings with precedence: defaults < config file < environment < explicit overrides."""
    config_path = config_path or os.getenv("LOCAL_SHELL_MCP_CONFIG")
    values = read_config_file(config_path)
    values.update(_env_overrides())
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return _prepare_settings(Settings(**values), create_dirs=create_dirs)


_configured_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings, optionally primed by configure_settings."""
    global _configured_settings
    if _configured_settings is None:
        _configured_settings = load_settings()
    return _configured_settings


def configure_settings(settings: Settings) -> None:
    """Install a fully resolved Settings object for subsequent get_settings calls."""
    global _configured_settings
    _configured_settings = settings


def clear_settings_cache() -> None:
    """Clear cached settings. Intended for tests and CLI reconfiguration."""
    global _configured_settings
    _configured_settings = None


def safe_settings_dump(settings: Settings | None = None) -> dict[str, Any]:
    """Return settings for diagnostics without exposing credentials or auth secrets."""

    data = (settings or get_settings()).model_dump(mode="json")
    for key in SENSITIVE_SETTING_KEYS:
        if key in data:
            value = data[key]
            if value in (None, "", []):
                data[key] = value
            else:
                data[key] = "<redacted>"
    return data
