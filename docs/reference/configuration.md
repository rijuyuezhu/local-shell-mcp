# Configuration reference

This page is rendered from [`generated/configuration.json`](generated/configuration.json), which is generated from the application settings registry.

Complete copy-editable examples are committed at the repository root as `.env.example` and `config.example.yaml`.

Settings resolve in this order:

```text
defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments
```

YAML config files use flat setting names such as `auth_mode` and `workspace_root`. Nested groups are not read by the application settings loader.

`audit_log_path` and `agent_config_dir` are derived from `state_dir` as `audit_log/audit.jsonl` and `agent_config`; they are not standalone settings.

<div class="generated-reference" data-reference-json="../generated/configuration.json">
Loading generated configuration reference...
</div>
