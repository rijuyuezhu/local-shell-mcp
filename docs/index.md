# local-shell-mcp

`local-shell-mcp` gives ChatGPT and other MCP clients controlled access to a local workspace. It exposes shell, filesystem, search, patch, Git-through-shell, todo, audit, remote-worker, and agent-bridge capabilities through a ChatGPT-compatible MCP server with OAuth support.

Use it when you want an AI coding agent to inspect a repository, edit files, run tests, and help with development without giving the model direct access to your host system.

## Start here

<div class="grid cards" markdown>

-   **Run with Docker**

    Start a contained workspace with Docker Compose, then expose `/mcp` through HTTPS for ChatGPT.

    [:octicons-arrow-right-24: Quickstart](getting-started/quickstart.md)

-   **Connect ChatGPT**

    Add the MCP endpoint as a custom connector and complete the built-in OAuth approval flow.

    [:octicons-arrow-right-24: Connector setup](getting-started/chatgpt-connector.md)

-   **Use remote workers**

    Invite a machine behind NAT, a firewall, or an HPC login node to connect back over outbound HTTPS.

    [:octicons-arrow-right-24: Remote workers](guides/remote-workers.md)

-   **Review safety**

    Understand what the connected model can do before mounting credentials or exposing the service publicly.

    [:octicons-arrow-right-24: Security](security.md)

</div>

## What you get

- A ChatGPT-compatible MCP endpoint at `/mcp`.
- Built-in OAuth for public deployments.
- Read-only `search` and `fetch` tools for regular connector clients.
- Full coding-agent tools for Developer Mode and other full MCP clients.
- A Docker image with common development, shell, document, and data-processing tooling.
- Optional remote-worker mode for machines that can only make outbound HTTP(S) connections.
- Optional agent capability bridge for externally synced MCP servers and skills.
- Complete short-term JSONL audit logging under the configured state directory.
- A VS Code extension that can start the server for the current workspace.

## Common paths

| Goal | Read this |
|---|---|
| First local deployment | [Quickstart](getting-started/quickstart.md) |
| Docker Compose details | [Docker Compose](getting-started/docker-compose.md) |
| ChatGPT connector setup | [ChatGPT connector](getting-started/chatgpt-connector.md) |
| HTTPS tunnel setup | [Cloudflare Tunnel](getting-started/cloudflare-tunnel.md) |
| Run from VS Code | [VS Code](getting-started/vscode.md) |
| Work with a remote machine | [Remote workers](guides/remote-workers.md) |
| Add external MCP servers or skills | [Agent capability bridge](guides/agent-bridge.md) |
| Configure the server | [Configuration reference](reference/configuration.md) |
| Understand all tools | [Tools reference](reference/tools.md) |
| Debug a broken setup | [Troubleshooting](troubleshooting.md) |

## Safety model

This project intentionally exposes powerful tools. Treat any connected model as able to read and modify the configured workspace, execute commands, use mounted credentials, and operate remote workers you invite.

Default safeguards include workspace path restrictions, timeout and output limits, default command/path denylists, audit logs, and OAuth for public connector use. Full-container mode disables built-in path and command restrictions and should only be used in disposable containers or VMs.
