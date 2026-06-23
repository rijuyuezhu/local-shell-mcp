# ChatGPT connector

`local-shell-mcp` can be added to ChatGPT as a custom MCP connector. Public deployments should use the built-in OAuth flow.

## Before adding the connector

Confirm:

1. The public HTTPS origin routes to the server.
2. `LOCAL_SHELL_MCP_BASE_URL` exactly matches that origin.
3. `LOCAL_SHELL_MCP_AUTH_MODE=oauth` is set.
4. `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` is set to a long random value.
5. The health endpoint works:

    ```bash
    curl -i https://your-public-host.example.com/healthz
    ```

The MCP URL is:

```text
https://your-public-host.example.com/mcp
```

## Add the connector

1. Open ChatGPT settings and find Connectors or custom MCP connectors.
2. Add a custom MCP connector.
3. Use the MCP URL ending in `/mcp`.
4. Complete the OAuth approval flow with `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`.
5. Refresh the connector tool list after server or tool-surface changes.

Regular connector-style clients may expose only `search` and `fetch`. ChatGPT Developer Mode and full MCP clients can expose the complete shell, filesystem, patch, remote-worker, and agent-bridge tools.

## Test prompt

```text
Use local-shell-mcp. Run session_start with workdir "." and summarize the returned session_id, workdir, git status, and instruction file paths. Do not edit files yet.
```

Then:

```text
Use local-shell-mcp to run pwd and tell me the output.
```

## OAuth behavior

On first connection, ChatGPT opens `/oauth/authorize`. After approval, the client exchanges the authorization code for a bearer token and calls `/mcp` with `Authorization: Bearer ...`.

Bearer tokens expire after `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S`. Authorization codes expire after `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S`.

## Common connector mistakes

- The connector URL omits `/mcp`.
- `LOCAL_SHELL_MCP_BASE_URL` includes `/mcp`; it should be the origin only.
- The public hostname in Cloudflare does not match `LOCAL_SHELL_MCP_BASE_URL`.
- The server was restarted with new tool settings, but the connector tool list was not refreshed.
- `LOCAL_SHELL_MCP_AUTH_MODE=none` is used on a public hostname.
