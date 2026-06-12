"""Backward-compatible imports for MCP application assembly."""

from __future__ import annotations

from .mcp.app import build_mcp, build_mcp_http_app, run_mcp, with_oauth_routes

__all__ = ["build_mcp", "build_mcp_http_app", "run_mcp", "with_oauth_routes"]
