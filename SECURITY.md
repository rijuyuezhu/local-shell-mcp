# Security Policy

`local-shell-mcp` exposes shell execution to an AI client. It must be treated as a high-risk administrative interface.

## Recommended deployment

- Run inside a disposable container or VM.
- Expose public deployments through HTTPS with `LOCAL_SHELL_MCP_AUTH_MODE=oauth`; Cloudflare Tunnel is fine, but Cloudflare Access is optional and not the built-in auth layer.
- Do not mount Docker socket.
- Do not mount host root.
- Do not mount unrestricted SSH keys or all of `~/.ssh`.
- Use single-repository deploy keys or short-lived GitHub App installation tokens.
- Leave `allow_full_container=false` by default.
- Review audit logs after each session.

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` is an explicit full-control mode. It
disables built-in command and path denylists and adds auto-approval hints for
command-capable tools. In the Docker image, the server still normally runs as the
`agent` user after entrypoint setup; that user has passwordless `sudo` for
commands that intentionally need root. Set `DOCKER_RUN_AS_ROOT=true` only when
the server process itself must run as root in a disposable container or VM.

## Threats considered

- Prompt injection in repository files.
- Malicious command execution by an over-capable model.
- Secret exfiltration from mounted files or environment variables.
- Host takeover via Docker socket or privileged mounts.
- Accidental destructive commands.

## Reporting

Open an issue or contact the maintainer privately if this is used in a sensitive environment.
