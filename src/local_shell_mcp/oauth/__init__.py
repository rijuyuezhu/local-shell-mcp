"""Layered OAuth support for HTTP and MCP transports.

The package is split by responsibility:

- ``oauth.http`` contains Starlette/FastAPI route and middleware adapters.
- ``oauth.core`` contains local OAuth state, policy, URL helpers, and services.
- ``oauth.protocol`` contains Authlib/PyJWT adapters and credential codecs.

See ``docs/security.md#oauth-security`` before changing this package. The
implementation comments call out where code intentionally follows that security
model and the MCP authorization profile.
"""
