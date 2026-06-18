# VS Code

The VS Code extension is a thin wrapper around the `local-shell-mcp` server. It starts the server with the current VS Code workspace as the controlled workspace and gives you commands to copy the MCP URL and a setup prompt.

## Install

Install the server first:

```bash
pipx install local-shell-mcp
# or: pip install local-shell-mcp
```

Then install the VS Code extension package from the GitHub release assets. Configure `local-shell-mcp.executablePath` if the executable is not on `PATH`.

## Basic flow

1. Open a project folder in VS Code.
2. Run **local-shell-mcp: Start Server** from the command palette.
3. Run **local-shell-mcp: Copy MCP URL** and paste it into your MCP client.
4. Run **local-shell-mcp: Copy ChatGPT Setup Prompt** when starting a coding session.

## Recommended settings

For direct host usage, keep `local-shell-mcp.allowFullControl` disabled so tools stay scoped to the selected workspace root.

Use `local-shell-mcp.authMode = oauth` when connecting ChatGPT through a public HTTPS tunnel. Use `none` only for trusted localhost testing.

If ChatGPT cannot reach your local machine directly, expose `127.0.0.1:8765` through an HTTPS tunnel and set `local-shell-mcp.baseUrl` to that origin. The MCP endpoint is then:

```text
https://your-public-origin.example.com/mcp
```

## Commands

- `local-shell-mcp: Start Server`
- `local-shell-mcp: Stop Server`
- `local-shell-mcp: Restart Server`
- `local-shell-mcp: Show Server Status`
- `local-shell-mcp: Copy MCP URL`
- `local-shell-mcp: Copy ChatGPT Setup Prompt`
- `local-shell-mcp: Open Guide`
