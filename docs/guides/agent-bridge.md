# Agent capability bridge

The agent capability bridge exposes extra capabilities from a server-side config directory. It can surface external MCP servers and Markdown skills through `local-shell-mcp`.

Use it when the control server should provide a stable set of additional tools or reusable instructions without asking the user to configure every MCP client separately.

## Directory layout

The bridge reads from `agent_config` under `LOCAL_SHELL_MCP_STATE_DIR`:

```text
/path/to/workspace/.local-shell-mcp/agent_config/
  config.json
  skills/
    paper-writer/
      SKILL.md
      template.md
```

For the default workspace state directory, the server path is:

```text
/workspace/.local-shell-mcp/agent_config
```

The server reads this directory at runtime. Treat it as configuration input and review external MCP server definitions before enabling them.

## `config.json`

Minimal config:

```json
{
  "version": 1
}
```

Example with stdio MCP, HTTP MCP, skills, and dynamic tools:

```json
{
  "version": 1,
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "github-mcp-server",
      "args": ["stdio"],
      "env": {
        "EXAMPLE_ENV_VALUE": "replace-me"
      }
    },
    "docs": {
      "type": "http",
      "url": "https://docs.example.com/mcp",
      "headers": {
        "X-Example-Header": "replace-me"
      },
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

Supported MCP server `type` values are `stdio`, `http`, and `sse`.

Values in `env`, `headers`, status output, and error payloads are redacted on a best-effort basis, but the config directory should still be protected like sensitive application configuration.

## Skills

A skill is a directory containing `SKILL.md`:

```text
skills/debugging/SKILL.md
```

Example:

```markdown
# Debugging

Use this skill for debugging failing tests. First reproduce the failure, then inspect the smallest relevant code path, then propose a minimal fix.
```

The skill name is derived from the directory name. Use `list_agent_skills` to see exact names, then `activate_agent_skill` to load one skill.

When dynamic skill tools are enabled, a skill such as `paper-writer` can also appear as a first-class MCP tool named like `activate_skill__paper_writer`.

## Bridge tools

| Tool | Use |
|---|---|
| `agent_config_status` | Show config path, manifest status, discovered skill count, MCP server status, dynamic-tool flags, and redacted errors. |
| `list_agent_skills` | List discovered skills without loading their content. |
| `activate_agent_skill` | Load one skill by exact name. |
| `list_agent_mcp_servers` | List configured upstream MCP servers and availability. |
| `list_agent_mcp_tools` | List tools exposed by one or all configured upstream MCP servers. |
| `call_agent_mcp_tool` | Call a tool from a configured upstream MCP server. |

Recommended client flow:

```text
Use local-shell-mcp to run agent_config_status, list available agent skills and MCP servers, then tell me which extra capabilities are available.
```

Before calling an upstream tool, list the server tools first:

```text
Use local-shell-mcp to list tools for the agent MCP server named docs, then call its search tool with query "deployment".
```

## Dynamic tools

Dynamic tools let discovered skills and upstream MCP tools appear directly in the MCP tool list. They are controlled by two layers:

1. Application settings: `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` and `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS`.
2. Manifest flags: `dynamicTools.mcp` and `dynamicTools.skills`.

Disable dynamic tools when the client should use only the fixed bridge tools instead of a changing tool surface.

## Settings

| Setting | Default | Meaning |
|---|---:|---|
| `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | `true` | Enable agent bridge tools |
| `LOCAL_SHELL_MCP_STATE_DIR` | `/workspace/.local-shell-mcp` | Runtime state root; `agent_config` is read from this directory |
| `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | `5` | Probe timeout for external MCP servers |
| `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | `60` | External MCP tool-call timeout |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | `true` | Register dynamic upstream MCP tools |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS` | `true` | Register dynamic skill tools |

## Notes

- Stdio MCP server commands run in the server environment. In Docker, that means inside the container. In local source/binary deployments, that means on the host running `local-shell-mcp`.
- Network MCP servers use the server's network path, not the ChatGPT client's network path.
- Review tool names and descriptions before exposing dynamic tools to a client.
