# ChatGPT connector

`local-shell-mcp` is designed to work as a ChatGPT custom MCP connector. Public deployments should use the built-in OAuth flow.

## Server requirements

Before adding the connector, confirm:

1. The server is reachable through a public HTTPS origin.
2. `LOCAL_SHELL_MCP_BASE_URL` exactly matches that public origin.
3. `LOCAL_SHELL_MCP_AUTH_MODE=oauth` is set for public access.
4. `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` is set to a long random value.

The MCP URL is:

```text
https://your-public-host.example.com/mcp
```

## Add the connector

1. Start `local-shell-mcp`.
2. In ChatGPT settings, open Connectors.
3. Enable Developer Mode under Advanced when you need the full coding-agent tool surface.
4. Add a custom MCP connector.
5. Use the MCP URL:

    ```text
    https://your-public-host.example.com/mcp
    ```

6. Complete the OAuth approval flow by entering `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`.
7. Refresh the connector tool list after server changes.

Regular connector clients can use the read-only `search` and `fetch` tools. Full shell, filesystem, patch, and remote-worker tools require Developer Mode or another full MCP client.

## Test the connector

After connecting, use a low-risk prompt:

```text
Use local-shell-mcp to run environment_info and summarize the workspace root, auth mode, and environment probe.
```

Then try:

```text
Use local-shell-mcp to run pwd and tell me the output.
```

## OAuth behavior

On first connection, ChatGPT opens `/oauth/authorize`. After you approve with the admin PIN, ChatGPT exchanges the authorization code for a bearer token and calls `/mcp` with an `Authorization: Bearer ...` header.

Bearer tokens expire after `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S`. The authorization code lifetime is controlled by `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S`.

## Common connector mistakes

- The public base URL has a trailing path or does not match the tunnel hostname.
- The connector URL omits `/mcp`.
- Developer Mode is disabled, so only read-only connector tools appear.
- The server was restarted with new tool settings, but ChatGPT's connector tool list was not refreshed.
- `LOCAL_SHELL_MCP_AUTH_MODE=none` is used on a public hostname. Do not do this.
