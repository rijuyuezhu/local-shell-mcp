# Configuration reference

This page is rendered from [`generated/configuration.json`](generated/configuration.json), which is generated from the application settings registry.

Complete copy-editable examples are committed at the repository root as `.env.example` and `config.example.yaml`.

Settings resolve in this order:

```text
defaults < config file < WORKGATE_* environment variables < CLI arguments
```

YAML config files use flat setting names such as `auth_mode` and `workspace_root`. Nested groups are not read by the application settings loader.

`audit_log_path`, `agent_config_dir`, and the private Agent Bridge credential directory are derived from `state_dir` as `audit_log/audit.jsonl`, `agent_config`, and `agent_auth`; they are not standalone settings.

<div class="generated-reference" data-reference-json="../generated/configuration.json">
Loading generated configuration reference...
</div>
