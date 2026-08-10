# Agent capability bridge

The Agent Bridge makes reusable Skills and selected upstream MCP servers available through `local-shell-mcp`. Use it when several clients should share the same server-managed capabilities.

## Configuration directory

Public configuration lives under the service state directory:

```text
/workspace/.local-shell-mcp/agent_config/
  config.json
  skills/
    debugging/
      SKILL.md
```

Credentials are managed separately by the CLI. Do not put new tokens or passwords directly in `config.json`.

The bridge also discovers project Skills from `<workdir>/.agents/skills` and user Skills from `~/.config/agents/skills`. A project Skill with the same directory name takes priority for that session.

## Minimal configuration

A minimal `config.json` is:

```json
{
  "version": 1
}
```

Example with one upstream MCP server and managed Skills:

```json
{
  "version": 1,
  "mcpServers": {
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

Supported upstream types are `stdio`, `http`, and `sse`. Review every command, URL, tool description, and requested scope before enabling a server.

## Add a Skill

Create a directory containing `SKILL.md`:

```text
agent_config/skills/debugging/SKILL.md
```

```markdown
# Debugging

Reproduce the failure first, inspect the smallest relevant code path, and verify a minimal fix with focused tests.
```

Use `list_agent_skills` to see discovered names and sources, then `activate_agent_skill` to load one. Related files returned by a Skill can be read with `read_agent_skill_file`.

When dynamic Skill tools are enabled, selected Skills also appear directly in the MCP tool list.

## Store a static secret

Secret references are valid only when the same server uses `auth.mode="secret"`. For example, this complete entry configures a server named `github` with a managed API-key header:

```json
{
  "version": 1,
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://github.example.com/mcp",
      "headers": {
        "X-API-Key": {"secret": "github_token"}
      },
      "auth": {"mode": "secret"},
      "enabled": true
    }
  }
}
```

Set the referenced value through standard input so it does not appear in the command arguments. The server name in the secret command must match the `mcpServers` key:

```bash
printf '%s\n' "$GITHUB_TOKEN" | local-shell-mcp mcp secret set github github_token --stdin
local-shell-mcp mcp secret list github
local-shell-mcp mcp secret delete github github_token
```

## Authorize an OAuth server

```bash
local-shell-mcp mcp auth docs
local-shell-mcp mcp auth docs --status
local-shell-mcp mcp auth docs --logout
```

Use `--no-open` when the CLI should print the authorization URL instead of opening a browser.

## Use bridge capabilities

Start by asking the client to show what is available:

```text
Use local-shell-mcp to check Agent Bridge status, list available Skills and upstream MCP servers, and summarize the extra capabilities.
```

Before calling an upstream tool, list that server's tools and review the selected tool name and description.

Dynamic tools are convenient, but they make the exposed tool list change with configuration. Disable them when clients should use only the fixed bridge tools.

## Security notes

- Stdio servers run in the `local-shell-mcp` server environment.
- HTTP and SSE servers use the server's network access, not the MCP client's.
- An upstream server can use any secret or OAuth scope granted to it. Configure only trusted servers and use the narrowest credentials possible.
- Keep the entire service state directory private and back it up only through a secure process.

See [Configuration](../reference/configuration.md) for settings, [Tool reference](../reference/tools.md) for exact bridge tools, and [Development](../development.md) for implementation guidance.
