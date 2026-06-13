# Agent capability bridge

The agent capability bridge exposes externally synced agent capabilities from a read-only config directory inside the container. It can surface external MCP servers and skills through `local-shell-mcp`.

## Directory layout

With the default Docker Compose layout, write files on the host under:

```text
workspaces/default/.local-shell-mcp/agent_config/
  config.json
  skills/
    <skill-name>/
      SKILL.md
```

The container reads the same files from:

```text
/workspace/.local-shell-mcp/agent_config
```

The default Compose workspace mount is read-write, but `local-shell-mcp` does not mutate this directory. Mount it read-only in stricter deployments.

## Example config

```json
{
  "version": 1,
  "mcpServers": {
    "docs": {
      "type": "http",
      "url": "https://example.com/mcp",
      "enabled": true
    }
  },
  "skills": {
    "enabled": true,
    "directory": "skills"
  },
  "dynamicTools": {
    "mcp": true,
    "skills": true
  }
}
```

## Bridge tools

| Tool | Purpose |
|---|---|
| `agent_config_status` | Show loaded config, discovered skills, MCP servers, dynamic tools, and probe status with secrets redacted. |
| `activate_agent_skill` | Return the content of a discovered `SKILL.md`. |
| `call_agent_mcp_tool` | Call a configured external MCP tool through the bridge. |

When dynamic tools are enabled in both environment settings and the bridge manifest, discovered skills and external MCP tools can appear as first-class MCP tools.

## Settings

| Variable | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | `true` | Enable agent bridge tools |
| `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `/workspace/.local-shell-mcp/agent_config` | Read-only capability config directory |
| `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | `5` | Probe timeout for external MCP servers |
| `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | `60` | External MCP tool-call timeout |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | `true` | Register dynamic MCP bridge tools |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS` | `true` | Register dynamic skill bridge tools |

## Notes

Stdio MCP server commands run inside the container for Docker deployments. Docker-free binary deployments run them in the same environment as `local-shell-mcp`, which may be the host.
