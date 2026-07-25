#!/usr/bin/env python3
"""Build one verified platform wheel with the native OpenTUI payload."""

from local_shell_mcp.release.platform_wheel import main

if __name__ == "__main__":
    raise SystemExit(main())
