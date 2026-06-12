"""Backward-compatible imports for HTTP REST application assembly."""

from __future__ import annotations

from .http.app import build_http_app, run_http

__all__ = ["build_http_app", "run_http"]
