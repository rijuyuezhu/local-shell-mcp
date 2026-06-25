"""Starlette/FastAPI adapters for OAuth HTTP endpoints and middleware.

Modules in this package should be thin: parse inbound HTTP requests, call
``oauth.core`` services or ``oauth.protocol`` validators, and convert results
into Starlette responses without embedding protocol or policy logic.
"""
