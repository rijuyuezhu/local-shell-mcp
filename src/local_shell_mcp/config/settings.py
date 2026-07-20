"""Runtime settings. It provides configuration for the local shell MCP server."""

import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_WORKSPACE_ROOT = Path("/workspace")
DEFAULT_STATE_DIR = DEFAULT_WORKSPACE_ROOT / ".local-shell-mcp"
AUDIT_LOG_STATE_DIR_NAME = "audit_log"
AGENT_CONFIG_STATE_DIR_NAME = "agent_config"
ENV_PREFIX = "LOCAL_SHELL_MCP_"
_RESERVED_UI_PATHS = (
    "/api",
    "/downloads",
    "/healthz",
    "/mcp",
    "/oauth",
    "/openapi.json",
    "/readyz",
    "/redoc",
    "/remote",
    "/docs",
)


def _split_csv(value: str | list[str] | None) -> list[str]:
    """Normalize comma-delimited environment values into list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [x.strip() for x in value.split(",") if x.strip()]


def normalize_ui_path(value: str) -> str:
    """Normalize and validate the browser UI mount path."""
    raw = str(value or "").strip()
    if not raw.startswith("/"):
        raise ValueError("ui_path must start with '/'")
    if any(character in raw for character in ("?", "#", "\\")):
        raise ValueError("ui_path must be a plain URL path")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(
            "ui_path must identify a non-root path without dot segments"
        )
    if any(not re.fullmatch(r"[A-Za-z0-9._~-]+", part) for part in parts):
        raise ValueError(
            "ui_path segments may contain only URL-safe ASCII characters"
        )
    normalized = "/" + "/".join(parts)
    for reserved in _RESERVED_UI_PATHS:
        if normalized == reserved or normalized.startswith(reserved + "/"):
            raise ValueError(
                f"ui_path conflicts with reserved service path: {reserved}"
            )
    return normalized


class Settings(BaseSettings):
    """Runtime settings.

    Environment variables use the LOCAL_SHELL_MCP_ prefix. Optional YAML config can
    be supplied with --config or LOCAL_SHELL_MCP_CONFIG. Effective precedence is:
    defaults < config file < environment variables < CLI overrides.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, extra="ignore", use_attribute_docstrings=True
    )
    """Pydantic settings configuration for environment loading."""

    # Server.
    mode: Literal["mcp", "http", "both", "stdio"] = "mcp"
    """Server transport mode."""
    host: str = "0.0.0.0"
    """Bind host for HTTP/MCP transports."""
    port: int = 8765
    """Bind port for HTTP/MCP transports."""

    # Human interface.
    ui_enabled: bool = True
    """Mount the browser Human UI and its authenticated API on the HTTP server."""
    ui_path: str = "/ui"
    """Non-root URL path where the browser Human UI is mounted."""
    ui_terminal_idle_timeout_s: int = 3600
    """Idle timeout for authenticated Human UI terminal WebSockets; 0 disables idle expiry."""
    ui_terminal_max_connections: int = 8
    """Maximum concurrent Human UI terminal WebSocket connections."""

    # Paths and state.
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT
    """Root directory for workspace."""
    state_dir: Path = DEFAULT_STATE_DIR
    """Directory for runtime state. Including audit logs, temporary files, and config"""

    # Authentication and OAuth.
    auth_mode: Literal["none", "oauth"] = "oauth"
    """Authentication mode. Do not expose public services with none."""
    auth_bypass_localhost: bool = False
    """Allow localhost requests without bearer authentication. Keep disabled when exposing HTTP through proxies or shared hosts."""
    mcp_session_idle_timeout_s: int = 180
    """Idle timeout for stateful Streamable HTTP MCP sessions in seconds."""
    mcp_max_sessions: int = 1024
    """Maximum concurrent stateful Streamable HTTP MCP sessions."""
    base_url: str | None = None
    """Externally reachable base URL used for OAuth metadata, callbacks, and generated links. If unset, URLs fall back to the bind host and port; configure this before exposing the service behind a proxy or public hostname."""
    oauth_issuer: str | None = None
    """Override URL for OAuth issuer metadata; usually derived from base_url."""
    oauth_resource: str | None = None
    """Override URL for OAuth resource metadata; usually derived from base_url plus /mcp."""
    oauth_admin_pin: str | None = None
    """Admin PIN required to approve OAuth authorization. Public OAuth URLs require a non-placeholder value of at least 8 characters."""
    oauth_access_token_ttl_s: int = 3600
    """Bearer token lifetime in seconds. After this time, the token must be re-authorized and refreshed."""
    oauth_code_ttl_s: int = 300
    """OAuth authorization-code lifetime in seconds. The authorization must be done within this time."""
    oauth_max_pending_codes: int = 2048
    """Maximum unused, unexpired OAuth authorization codes kept in memory; set to 0 to disable this capacity limit."""
    oauth_client_ttl_s: int = 86400
    """Pending OAuth client registration lifetime in seconds. Approved clients are persisted without this TTL; set to 0 to disable pending expiration."""
    oauth_max_dynamic_clients: int = 256
    """Maximum pending OAuth client registrations kept in memory. Approved clients do not count; set to 0 to disable this capacity limit."""
    oauth_registration_max_body_bytes: int = 16384
    """Maximum JSON body size accepted by dynamic OAuth client registration."""
    oauth_registration_max_redirect_uris: int = 10
    """Maximum redirect URIs accepted in one dynamic OAuth client registration."""
    oauth_registration_max_redirect_uri_chars: int = 2048
    """Maximum length of each dynamic OAuth client redirect URI."""
    oauth_registration_max_client_name_chars: int = 200
    """Maximum length of a dynamic OAuth client display name."""

    # Safety and resource limits.
    allow_full_control: bool = False
    """Disable built-in workspace and command restrictions; use only in disposable containers or VMs. MCP safety annotations remain conservative in this mode."""
    """Allow network-capable operations."""
    relaxed_client_tool_hints: bool = False
    """Deprecated compatibility flag. MCP safety annotations remain semantic and mode-independent."""
    tool_timeout_s: float = 60
    """Base MCP/HTTP tool watchdog timeout in seconds. Shell execution tools receive additional bounded cleanup time beyond run_shell_max_timeout_s."""
    run_shell_default_timeout_s: int = 10
    """Default timeout for bounded shell command calls in seconds."""
    run_shell_max_timeout_s: int = 60
    """Maximum timeout accepted by bounded shell command calls in seconds."""
    max_output_bytes: int = 200_000
    """Command output limit in bytes."""
    max_job_log_bytes: int = 10_000_000
    """Maximum retained output bytes for one tracked background-job attempt."""
    max_jobs: int = 1_000
    """Maximum retained tracked-job records; active jobs are never pruned."""
    max_file_read_bytes: int = 512_000
    """Per-file read limit in bytes."""
    max_view_image_bytes: int = 20 * 1024 * 1024
    """Maximum raw bytes accepted by the native MCP image viewer."""
    max_skills: int = 256
    """Maximum number of discovered Skills across all configured sources."""
    max_skill_related_files: int = 1_000
    """Maximum related files returned for one Skill."""
    max_skill_scan_entries: int = 5_000
    """Maximum filesystem entries inspected during one Skill registry scan."""
    max_skill_path_bytes: int = 200_000
    """Maximum UTF-8 bytes used by returned related Skill paths."""
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
    """Maximum files allowed in one internal multi-file read operation."""
    max_read_many_total_bytes: int = 5_000_000
    """Maximum total byte limit for one internal multi-file read operation."""
    max_todos: int = 1_000
    """Todo-list item limit."""
    max_todo_bytes: int = 1_000_000
    """Todo-list total byte limit."""
    max_http_request_bytes: int = 16_000_000
    """Maximum inbound HTTP request-body bytes; 0 disables the shared limit."""
    max_audit_log_bytes: int = 20_000_000
    """Maximum active audit JSONL bytes before atomic recent-record retention."""
    max_audit_event_bytes: int = 1_000_000
    """Maximum encoded bytes retained for one audit event before preview truncation."""
    max_tmp_files: int = 500
    """Temporary-file count limit. When exceeded, old files are deleted."""
    max_tmp_bytes: int = 50_000_000
    """Temporary-file byte limit. When exceeded, old files are deleted."""
    max_transfer_archive_entries: int = 100_000
    """Maximum entries accepted from one transferred archive."""
    max_transfer_unpacked_bytes: int = 10_000_000_000
    """Maximum declared regular-file bytes accepted while unpacking an archive."""
    max_concurrent_commands: int = 4
    """Concurrent command limit."""
    max_tmux_sessions: int = 16
    """Persistent shell limit."""
    file_download_enabled: bool = True
    """Enable download links created by protected tools."""
    file_download_default_ttl_s: int = 3600
    """Default lifetime for file download links in seconds."""
    file_download_max_ttl_s: int = 604800
    """Maximum lifetime accepted for file download links in seconds."""
    file_download_default_max_downloads: int = 0
    """Default download-count limit for file links; 0 means unlimited until expiry."""
    file_download_max_file_bytes: int = 0
    """Maximum file size allowed for download links; 0 disables this size limit."""
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
    """Comma-separated command denylist in env/CLI, or a YAML list in config files. Cleared when full-control mode is enabled."""
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
    """Comma-separated path denylist in env/CLI, or a YAML list in config files. Cleared when full-control mode is enabled."""

    # Remote workers.
    remote_enabled: bool = True
    """Enable remote worker routes and MCP tools."""
    remote_invite_ttl_s: int = 600
    """One-time remote worker invite lifetime in seconds."""
    remote_poll_timeout_s: int = 25
    """Remote worker long-poll heartbeat timeout in seconds."""
    remote_job_timeout_s: int = 3600
    """Control-side remote job result timeout in seconds."""
    remote_max_pending_jobs: int = 64
    """Maximum queued or in-flight remote jobs allowed per worker."""

    # Agent capability bridge.
    agent_bridge_enabled: bool = True
    """Enable agent capability bridge tools."""
    agent_mcp_probe_timeout_s: int = 5
    """Agent MCP server probe timeout in seconds."""
    agent_mcp_call_timeout_s: int = 60
    """Agent MCP tool-call timeout in seconds."""
    agent_dynamic_mcp_tools: bool = True
    """Register dynamic MCP bridge tools."""
    agent_dynamic_skill_tools: bool = True
    """Register dynamic skill bridge tools."""

    # Tool executables.
    shell_executable: str = "/bin/bash"
    """Shell executable used for shell commands."""
    tmux_bin: str = "tmux"
    """tmux executable."""
    rg_bin: str = "rg"
    """ripgrep executable."""
    python_bin: str = "python3"
    """Python executable."""

    @property
    def audit_log_path(self) -> Path:
        """Path to the JSONL audit log, derived from state_dir."""
        return self.state_dir / AUDIT_LOG_STATE_DIR_NAME / "audit.jsonl"

    @property
    def agent_config_dir(self) -> Path:
        """Read-only capability config directory, derived from state_dir."""
        return self.state_dir / AGENT_CONFIG_STATE_DIR_NAME

    @property
    def resolved_base_url(self) -> str:
        """Configured base_url, or a local HTTP URL derived from host and port."""
        if self.base_url:
            return self.base_url.rstrip("/")
        host = self.host
        if host in {"", "0.0.0.0", "::"}:
            host = "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port}"

    @field_validator(
        "workspace_root",
        "state_dir",
        mode="before",
    )
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        """Expand user and environment variables for path settings before validation."""
        expanded = os.path.expandvars(os.path.expanduser(str(value)))
        return Path(os.path.abspath(expanded))

    @field_validator("ui_path", mode="before")
    @classmethod
    def validate_ui_path(cls, value: str) -> str:
        """Reject root, traversal, and service-reserved Human UI paths."""
        return normalize_ui_path(value)

    @field_validator("ui_terminal_idle_timeout_s")
    @classmethod
    def validate_ui_terminal_idle_timeout(cls, value: int) -> int:
        """Reject negative Human UI terminal idle timeouts."""
        if value < 0:
            raise ValueError("ui_terminal_idle_timeout_s must be non-negative")
        return value

    @field_validator("ui_terminal_max_connections")
    @classmethod
    def validate_ui_terminal_max_connections(cls, value: int) -> int:
        """Bound concurrent Human UI terminal WebSocket connections."""
        if not 1 <= value <= 128:
            raise ValueError(
                "ui_terminal_max_connections must be between 1 and 128"
            )
        return value

    @field_validator("command_denylist", "path_denylist", mode="before")
    @classmethod
    def split_csv_fields(cls, value: str | list[str] | None) -> list[str]:
        """Normalize comma-delimited restriction lists supplied through environment variables."""
        return _split_csv(value)

    @model_validator(mode="after")
    def disable_builtin_restrictions_in_full_container_mode(self) -> Settings:
        """Remove built-in command and path restrictions when full-control mode is explicitly enabled."""
        if self.allow_full_control:
            self.command_denylist = []
            self.path_denylist = []
        return self


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
    return loaded


def env_overrides() -> dict[str, Any]:
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
    """Create runtime directories when requested."""
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
    """Load settings with precedence: defaults < config file < environment < explicit overrides. Here the explicit overrides usually come from the CLI."""
    config_path = config_path or os.getenv("LOCAL_SHELL_MCP_CONFIG")
    values = read_config_file(config_path)
    values.update(env_overrides())
    if overrides:
        values.update(overrides)
    return _prepare_settings(Settings(**values), create_dirs=create_dirs)


_configured_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings, optionally primed by configure_settings. If no settings are cached, a new one is loaded from load_settings without any CLI overrides."""
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
