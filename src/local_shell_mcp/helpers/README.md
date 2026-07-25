# Bundled helpers

Linux standalone releases generate a statically linked tmux helper below this
directory before PyInstaller builds the executable. Generated helper binaries
are intentionally excluded from Git, wheels, and source distributions.

At runtime, local-shell-mcp prefers an explicitly configured or system tmux and
uses the matching bundled helper only when the default `tmux` command is absent.
Docker images continue to use the distribution-provided tmux package.
