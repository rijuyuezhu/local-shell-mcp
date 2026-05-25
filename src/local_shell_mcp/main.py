from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from .auth import CloudflareAccessMiddleware
from .http_app import build_http_app
from .settings import get_settings
from .tools import build_mcp


def run_mcp() -> None:
    settings = get_settings()
    mcp = build_mcp()

    if settings.mode == "stdio":
        mcp.run(transport="stdio")
        return

    # Prefer an ASGI app when the installed MCP SDK exposes one, because then we can add
    # Cloudflare Access middleware at the origin. If unavailable, fall back to FastMCP's
    # built-in streamable-http transport; use Cloudflare Access at the edge in that case.
    for attr in ("streamable_http_app", "sse_app"):
        if hasattr(mcp, attr):
            app = getattr(mcp, attr)()
            if settings.auth_mode != "none":
                app.add_middleware(CloudflareAccessMiddleware)
            uvicorn.run(app, host=settings.host, port=settings.port)
            return

    try:
        mcp.run(transport="streamable-http")
    except TypeError:
        # Older SDKs may use sse.
        mcp.run(transport="sse")


def run_http() -> None:
    settings = get_settings()
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="local-shell-mcp")
    parser.add_argument("--mode", choices=["mcp", "http", "stdio"], default=None)
    parser.add_argument("--config", default=None, help="Path to config YAML")
    args = parser.parse_args(argv)
    if args.config:
        os.environ["LOCAL_SHELL_MCP_CONFIG"] = args.config
    if args.mode:
        os.environ["LOCAL_SHELL_MCP_MODE"] = args.mode

    settings = get_settings()
    if settings.mode == "http":
        run_http()
    elif settings.mode in {"mcp", "stdio"}:
        run_mcp()
    elif settings.mode == "both":
        raise SystemExit("mode=both is reserved for a future combined ASGI app; run separate mcp/http processes for now")
    else:
        raise SystemExit(f"Unsupported mode: {settings.mode}")


if __name__ == "__main__":
    main(sys.argv[1:])
