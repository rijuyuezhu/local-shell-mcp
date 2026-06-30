"""Remote-worker bootstrap package.

Importing this package is intentionally dependency-light. The executable worker
entrypoint lives in ``local_shell_mcp.remote_worker.__main__`` and installs
worker-only compatibility shims before loading the shared worker loop or tool
implementations.
"""
