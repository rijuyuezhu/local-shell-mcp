# Agent capability bridge

The agent capability bridge exposes extra capabilities from a managed server-side config directory. It can surface external MCP servers and Markdown skills through `local-shell-mcp`. Skills are discovered from ordered project/session, managed, and global registry sources.

Use it when the control server should provide a stable set of additional tools or reusable instructions without asking the user to configure every MCP client separately.

## Directory layout

The bridge reads public configuration from `agent_config` and keeps credentials in a separate private `agent_auth` directory under `LOCAL_SHELL_MCP_STATE_DIR`:

```text
/path/to/workspace/.local-shell-mcp/
  agent_config/
    config.json
    skills/
      paper-writer/
        SKILL.md
        template.md
  agent_auth/
    credentials.json
    credentials.lock
```

For the default workspace state directory, the server path is:

```text
/workspace/.local-shell-mcp/agent_config
```

The server reads this directory at runtime. Treat it as configuration input and review external MCP server definitions before enabling them.

Skill discovery uses these deduplicated sources in priority order:

1. Project/session: `<workdir>/.agents/skills`
2. Managed: `<agent_config_dir>/<skills.directory>`
3. Global: `$XDG_CONFIG_HOME/agents/skills`, or `~/.config/agents/skills` when `XDG_CONFIG_HOME` is unset or relative

The first valid Skill with a given directory name wins. A malformed higher-priority directory does not block a valid lower-priority Skill. The sources share the configured skill-count, scan-entry, and path-byte budgets, and duplicate or truncated entries are reported as bounded warnings. Symlinks and paths escaping their selected source root remain rejected.

When `session_id` is supplied to `list_agent_skills`, `activate_agent_skill`, or `read_agent_skill_file`, the project source is that explicit local session workdir. For a remote session, discovery and reads execute on the owning worker against its session workdir; source paths are never resolved on the control machine. Without `session_id`, the project source is `workspace_root`. Dynamic skill tools use that default workspace registry.

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
        "GITHUB_PERSONAL_ACCESS_TOKEN": {"secret": "github_token"}
      },
      "auth": {"mode": "secret"}
    },
    "docs": {
      "type": "http",
      "url": "https://docs.example.com/mcp",
      "auth": {
        "mode": "oauth",
        "scopes": ["tools.read"]
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

Strings in `env` and `headers` remain literal values for backward compatibility. An object such as `{"secret": "github_token"}` is resolved from the private credential store only immediately before the stdio, HTTP, or SSE transport is opened. Do not place new credentials directly in `config.json`.

## Credentials and OAuth

Each server can set `auth.mode` to `none`, `secret`, or `oauth`:

- `none` uses no Agent Bridge authentication. Literal headers and environment variables still work.
- `secret` requires at least one structured secret reference in `env` or `headers`.
- `oauth` is valid only for HTTP and SSE servers. Optional `auth.scopes` are sent to the authorization server.

Store and inspect static secrets without placing values in shell history or process arguments:

```bash
printf '%s\n' "$GITHUB_TOKEN" | local-shell-mcp mcp secret set github github_token --stdin
local-shell-mcp mcp secret list github
local-shell-mcp mcp secret delete github github_token
```

Authorize an OAuth server with a random loopback callback port:

```bash
local-shell-mcp mcp auth docs
local-shell-mcp mcp auth docs --no-open
local-shell-mcp mcp auth docs --status
local-shell-mcp mcp auth docs --logout
```

Authorization reuses the MCP SDK flow: protected-resource and authorization-server discovery, PKCE and state validation, optional dynamic client registration, token refresh, and persisted client/token metadata. A successful authorization performs a real `tools/list` probe. `--logout` attempts the advertised token revocation endpoint before removing local OAuth credentials and reports whether remote revocation succeeded, was unsupported, or failed.

The private store is a versioned, bounded JSON file protected by a cross-process lock and atomic replacement. On POSIX systems its directory is mode `0700` and its files are mode `0600`. Invalid, oversized, or corrupt state produces an explicit error and is never silently reset. Status and MCP payloads expose only auth mode, authorization state, expiry/status metadata, counts, and redacted errors; secret names are available only through the local administrative `mcp secret list` command.

Changing the private credential file participates in Agent Bridge registry fingerprinting, so secret updates, authorization, refresh, and logout become visible to dynamic tools without restarting the server.

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

The skill name is derived from the directory name. Use `list_agent_skills` to see exact names, selected `source`, and `source_path`, then pass the same optional `session_id` to `activate_agent_skill` or `read_agent_skill_file`.

When dynamic skill tools are enabled, a skill such as `paper-writer` can also appear as a first-class MCP tool named like `activate_skill__paper_writer`.

## Bridge tools

| Tool | Use |
|---|---|
| `agent_config_status` | Show config path, manifest status, discovered skill count, MCP server status, dynamic-tool flags, and redacted errors. |
| `list_agent_skills` | List discovered skills without loading their content. |
| `activate_agent_skill` | Load one skill by exact name. |
| `read_agent_skill_file` | Read one bounded related text file returned by `activate_agent_skill`. |
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
| `LOCAL_SHELL_MCP_STATE_DIR` | `/workspace/.local-shell-mcp` | Runtime state root; public `agent_config` and private `agent_auth` are derived from this directory |
| `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | `5` | Probe timeout for external MCP servers |
| `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | `60` | External MCP tool-call timeout |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | `true` | Register dynamic upstream MCP tools |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS` | `true` | Register dynamic skill tools |

## Notes

- Stdio MCP server commands run in the server environment. In Docker, that means inside the container. In local source/binary deployments, that means on the host running `local-shell-mcp`.
- Network MCP servers use the server's network path, not the ChatGPT client's network path.
- Review tool names and descriptions before exposing dynamic tools to a client.
- OAuth authorization is interactive only in the CLI. Normal server operation uses stored access/refresh credentials and never launches a browser.
- Secret values are injected into child-process environments or HTTP headers by design; an upstream MCP server can use or exfiltrate them. Configure only trusted servers and grant the narrowest scopes or tokens possible.
