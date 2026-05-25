# Security Policy

`local-shell-mcp` exposes shell execution to an AI client. It must be treated as a high-risk administrative interface.

## Recommended deployment

- Run inside a disposable container or VM.
- Expose only through Cloudflare Access.
- Do not mount Docker socket.
- Do not mount host root.
- Do not mount unrestricted SSH keys or all of `~/.ssh`.
- Use single-repository deploy keys or short-lived GitHub App installation tokens.
- Leave `allow_full_container=false` by default.
- Review audit logs after each session.

## Threats considered

- Prompt injection in repository files.
- Malicious command execution by an over-capable model.
- Secret exfiltration from mounted files or environment variables.
- Host takeover via Docker socket or privileged mounts.
- Accidental destructive commands.

## Reporting

Open an issue or contact the maintainer privately if this is used in a sensitive environment.
